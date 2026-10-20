#!/usr/bin/env python3
"""Draw Figure 5 from the saved response-conditioned fit and draw-wise estimates."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import warnings

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PYTENSOR_FLAGS", "cxx=,linker=py")
os.environ.setdefault("MPLBACKEND", "Agg")

import arviz as az
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.text import Text
import numpy as np

import model

HERE = Path(__file__).resolve().parent
STYLE_PATH = HERE / "style.json"


@dataclass(frozen=True)
class FigureData:
    ids: tuple[str, ...]
    human: dict[str, np.ndarray]
    predicted: dict[str, np.ndarray]
    delta_mean: np.ndarray
    delta_hdi: np.ndarray


def load_figure_data(report_dir: Path, trace_path: Path) -> FigureData:
    """Check cached predictions against their fit, data, and participant axes."""
    manifest = json.loads((report_dir / "provenance.json").read_text())
    trace_key = os.path.relpath(trace_path.resolve(), model.ROOT)
    if manifest["inputs"].get(trace_key) != model.sha256(trace_path):
        raise ValueError("Report and posterior hashes differ")
    for key, digest in manifest["inputs"].items():
        # Changes to renderer/report code do not alter stored probabilities.
        if key.endswith(".npy") or key.startswith("data/"):
            if model.sha256(model.ROOT / key) != digest:
                raise ValueError(f"Report input changed: {key}")
    with (report_dir / "participant_estimates.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    _, _, participants, s1, s2 = model.selected_data()
    ids = tuple(p["PROLIFIC_PID"] for p in participants)
    if tuple(r["subject"] for r in rows) != ids or manifest["selected_ids"] != list(ids):
        raise ValueError("Report/data participant order differs")
    trace = az.from_netcdf(trace_path)
    post = trace.posterior
    if (post.attrs.get("model_variant") != "response-gated-free"
            or tuple(post.subject.values) != ids
            or json.loads(post.attrs.get("selected_ids", "[]")) != list(ids)):
        raise ValueError("Wrong model or posterior participant alignment")
    if not model.diagnostics(trace)[0]["passed"]:
        raise ValueError("Posterior sampling diagnostics failed")
    delta = post["delta"].transpose("chain", "draw", "subject").values.reshape(-1, len(ids))
    delta_mean = delta.mean(0)
    delta_hdi = np.array([az.hdi(delta[:, j], hdi_prob=.95) for j in range(len(ids))])
    csv_values = lambda key: np.array([float(r[key]) for r in rows])
    np.testing.assert_allclose(csv_values("delta_mean"), delta_mean, rtol=0, atol=1e-12)
    np.testing.assert_allclose(
        np.column_stack([csv_values("delta_hdi_low"), csv_values("delta_hdi_high")]),
        delta_hdi, rtol=0, atol=1e-12)
    s1, s2 = np.asarray(s1), np.asarray(s2)
    n2 = s2.sum(2)
    human = {
        "MD": (s1[:, 0] + s1[:, 2]) / s1.sum(1),
        "CL": (s1[:, 0] + s1[:, 1]) / s1.sum(1),
        "changed": (s2[:, 0, 0] + s2[:, 2, 2]) / (n2[:, 0] + n2[:, 2]),
        "same": s2[:, 1, 1] / n2[:, 1],
    }
    predicted = {k: csv_values(f"model_{k}") for k in human}
    summary = json.loads((report_dir / "summary.json").read_text())
    for k, observed in human.items():
        np.testing.assert_allclose(csv_values(f"observed_{k}"), observed, rtol=0, atol=1e-12)
        if not np.isfinite(predicted[k]).all() or ((predicted[k] < 0) | (predicted[k] > 1)).any():
            raise ValueError(f"Invalid {k} probabilities")
        np.testing.assert_allclose(predicted[k].mean(),
                                   summary["accuracy_observed_scale"][k]["mean"], atol=1e-12)
        np.testing.assert_allclose(np.corrcoef(predicted[k], observed)[0, 1],
                                   summary["in_sample_correlations"][k], atol=1e-12)
    return FigureData(ids, human, predicted, delta_mean, delta_hdi)


def fonts_and_rc(style):
    for name in ["Lato-Regular.ttf", "Lato-Bold.ttf"]:
        font_manager.fontManager.addfont(HERE / "fonts" / name)
    try:
        font_manager.findfont(font_manager.FontProperties(family="Arial"),
                              fallback_to_default=False)
        tick_font = "Arial"
    except ValueError:
        tick_font = "Lato"
        warnings.warn("Arial is unavailable; Figure 5 tick and legend labels use bundled Lato.",
                      stacklevel=2)
    style["tick_font"] = tick_font
    fonts = {}
    for family in [style["text_font"], tick_font, "cmr10"]:
        path = Path(font_manager.findfont(font_manager.FontProperties(family=family),
                                          fallback_to_default=False))
        fonts[family] = {"filename": path.name, "sha256": model.sha256(path)}
    rc = {
        "font.family": style["text_font"], "text.color": style["text_color"],
        "axes.labelcolor": style["text_color"], "axes.titlecolor": style["text_color"],
        "mathtext.fontset": style["math_fontset"], "text.usetex": False,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path",
        "figure.facecolor": "white", "axes.facecolor": "white",
        "xtick.color": style["tick_color"], "ytick.color": style["tick_color"],
        "axes.unicode_minus": True,
    }
    return {"families": fonts, "tick_font": tick_font, "arial_fallback": tick_font != "Arial"}, rc


def rect_in_figure(rect, width, height):
    x, top, w, h = rect
    return [x / width, (height - top - h) / height, w / width, h / height]


def add_forest_ylabel(fig, style: dict):
    """Draw the axis label with a larger delta symbol and Lato text."""
    width, height = style["canvas_points"]
    x, top = style["forest_y_label_anchor_points"]
    size = style["sizes_points"]["forest_axis"]
    prop = font_manager.FontProperties(family=style["text_font"], size=size)
    renderer = fig.canvas.get_renderer()
    text_width = lambda s: renderer.get_text_width_height_descent(s, prop, False)[0] * 72 / fig.dpi
    prefix, suffix = "Ensemble Advantage (", ")"
    left, right = text_width(prefix), text_width(suffix)
    slot = style["forest_symbol_slot_points"] * size / 23
    start = height - top - (left + slot + right) / 2
    segments = [(prefix, left / 2, size),
                (r"$\delta$", left + slot / 2, style["sizes_points"]["forest_symbol"]),
                (suffix, left + slot + right / 2, size)]
    for text, along, fontsize in segments:
        fig.text(x / width, (start + along) / height, text, ha="center", va="center",
                 rotation=90, fontsize=fontsize, color=style["text_color"])


def render_figure(data: FigureData, style: dict, rc: dict):
    width, height = style["canvas_points"]
    divider = style["divider_x"]
    sizes, forest, accuracy = style["sizes_points"], style["forest"], style["accuracy"]
    with plt.rc_context(rc):
        fig = plt.figure(figsize=(width / 72, height / 72))
        top, bottom = style["divider_top_bottom"]
        fig.add_artist(Line2D([divider / width] * 2,
                             [1 - top / height, 1 - bottom / height],
                             transform=fig.transFigure, color=style["divider_color"],
                             linewidth=style["divider_width"]))
        for (x, y), letter in zip(style["panel_label_anchors_points"], ("A", "B")):
            fig.text(x / width, 1 - y / height, f"({letter})", va="top",
                     family="cmr10", fontsize=sizes["panel"], color=style["math_color"])
        correlations = {}
        axes = []
        for j, task in enumerate(style["tasks"]):
            key = task["key"]
            ax = fig.add_axes(rect_in_figure(style["accuracy_rects_points"][j], width,
                                            height), label=key)
            axes.append(ax)
            x, y = data.predicted[key], data.human[key]
            r = float(np.corrcoef(x, y)[0, 1])
            correlations[key] = r
            ax.set_axisbelow(True)
            ax.grid(True, which="both", color=accuracy["grid_color"], alpha=accuracy["grid_alpha"],
                    linewidth=accuracy["grid_width"])
            ax.scatter(x, y, s=accuracy["marker_area"], color=task["color"],
                       alpha=accuracy["marker_alpha"], edgecolors="white",
                       linewidth=accuracy["marker_edge_width"])
            ax.plot([0, 1], [0, 1], "--", color=accuracy["identity_color"],
                    linewidth=accuracy["identity_width"])
            ax.set(xlim=(0, 1), ylim=(0, 1), aspect="equal")
            ax.set_xticks(accuracy["ticks"], labels=accuracy["ticklabels"])
            ax.set_yticks(accuracy["ticks"], labels=accuracy["ticklabels"])
            ax.tick_params(length=6, width=1, labelsize=sizes["accuracy_tick"])
            if j % 2:
                ax.tick_params(axis="y", labelleft=False)
            for tick in ax.get_xticklabels() + ax.get_yticklabels():
                tick.set_fontfamily(style["tick_font"])
            for spine in ax.spines.values():
                spine.set_linewidth(accuracy["spine_width"])
                spine.set_color(accuracy.get("spine_color", "black"))
            ax.set_title(task["title"], fontsize=sizes["accuracy_title"], weight="bold", pad=10)
            ax.set_xlabel("Model Accuracy", fontsize=sizes["accuracy_axis"], labelpad=12)
            if j % 2 == 0:
                ax.set_ylabel("Human Accuracy", fontsize=sizes["accuracy_axis"], labelpad=17)
            ax.text(.05, .93, rf"$R = {r:.2f}$", transform=ax.transAxes, va="top",
                    fontsize=sizes["correlation"], color=style["math_color"])
        ax = fig.add_axes(rect_in_figure(style["forest_rect_points"], width, height), label="delta")
        axes.append(ax)
        order = np.argsort(data.delta_mean, kind="stable")
        x = np.arange(len(order))
        lo, hi = data.delta_hdi[order].T
        ax.vlines(x, lo, hi, color=forest["color"], alpha=forest["interval_alpha"],
                  linewidth=forest["interval_width"])
        ax.scatter(x, data.delta_mean[order], s=forest["marker_area"],
                   color=forest["color"], edgecolor="white",
                   linewidth=forest["marker_edge_width"], zorder=5)
        ax.axhline(0, color=forest["zero_color"], linestyle="--",
                   linewidth=forest["zero_width"])
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=forest["grid_color"], alpha=forest["grid_alpha"],
                linestyle="--", linewidth=1.5)
        ylo, yhi = forest["ylim"]
        if lo.min() < ylo or hi.max() > yhi:
            raise ValueError("Intervals exceed the reference axis; explicitly revise the style limits")
        ax.set(xlim=(-4, len(order) + 3), ylim=(ylo, yhi), xticks=[])
        ax.set_yticks(forest["yticks"])
        ax.tick_params(axis="y", length=0, pad=8, labelsize=sizes["forest_tick"])
        for tick in ax.get_yticklabels():
            tick.set_fontfamily(style["tick_font"])
            tick.set_color("#262626")
        ax.spines[["top", "right"]].set_visible(False)
        for side in ["left", "bottom"]:
            ax.spines[side].set_color(forest["spine_color"])
            ax.spines[side].set_linewidth(forest["spine_width"])
        ax.set_xlabel("Participants", fontsize=sizes["forest_axis"], labelpad=26)
        tx, ty = style["forest_title_anchor_points"]
        fig.text(tx / width, 1 - ty / height,
                 style["forest_title"], ha="center", va="top",
                 fontsize=sizes["forest_title"], weight="bold")
        add_forest_ylabel(fig, style)
        interval_handle = Line2D([0], [0], color=forest["color"],
                                 alpha=forest["interval_alpha"], linewidth=forest["interval_width"])
        mean_handle = Line2D([0], [0], color=forest["color"], marker="o", linestyle="none",
                             markeredgecolor="white", markersize=10)
        legend = ax.legend([interval_handle, mean_handle], ["95% HDI", "Posterior Mean"],
                           loc="upper left", frameon=True, fancybox=True, shadow=True,
                           prop={"family": style["tick_font"], "size": sizes["legend"]})
        legend.get_frame().set_edgecolor(forest["spine_color"])
        legend.get_frame().set_linewidth(1.6)
        for text in legend.get_texts():
            text.set_color("#262626")
        return fig, correlations, order, axes


def plot_figure(report_dir: Path, trace_path: Path, output_pdf: Path) -> dict:
    """Return correlations and font provenance after saving the vector PDF."""
    report_dir, trace_path, output_pdf = map(Path, (report_dir, trace_path, output_pdf))
    data = load_figure_data(report_dir, trace_path)
    style = json.loads(STYLE_PATH.read_text())
    fonts, rc = fonts_and_rc(style)
    fig, correlations, order, axes = render_figure(data, style, rc)
    with plt.rc_context(rc):
        fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.findobj(Text):
        if text.get_visible() and text.get_text():
            box = text.get_window_extent(renderer)
            if (box.x0 < -2 or box.y0 < -2 or box.x1 > fig.bbox.x1 + 2
                    or box.y1 > fig.bbox.y1 + 2):
                raise ValueError(f"Clipped figure text: {text.get_text()}")
    legend = axes[-1].get_legend().get_window_extent(renderer)
    intervals = axes[-1].collections[0].get_segments()
    for segment in intervals:
        coords = axes[-1].transData.transform(segment)
        if (legend.x0 <= coords[0, 0] <= legend.x1
                and coords[:, 1].max() >= legend.y0 and coords[:, 1].min() <= legend.y1):
            raise ValueError("Legend overlaps a credible interval")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(rc):
        fig.savefig(output_pdf, metadata={"Title": "Experiment 2 model results",
                                        "CreationDate": None, "ModDate": None})
    plt.close(fig)
    return {"correlations": correlations, "fonts": fonts,
            "participant_order": [data.ids[j] for j in order],
            "text_within_canvas": True, "individual_interval_bars": len(intervals)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=model.ROOT / "results/experiment2")
    parser.add_argument("--trace", type=Path, default=model.ROOT / "results/experiment2/trace.nc")
    parser.add_argument("--out", type=Path, required=True, help="Output vector PDF")
    args = parser.parse_args()
    result = plot_figure(args.report_dir, args.trace, args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
