#!/usr/bin/env python3
"""Calculate and check stimulus mass distributions."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats


ROOT = Path(__file__).resolve().parent

REFERENCE_MASS = 8.0
MASS_LEVELS = (
    2.0,
    2.31422047456544,
    2.677808202448944,
    3.0985192845333116,
    3.585328384551423,
    4.1486201777847675,
    4.800410878312412,
    5.554604570458625,
    6.427289812535059,
    7.437082840067251,
    8.0,
    8.60552468976146,
    9.957540715712186,
    11.521972300310074,
    13.332192102376712,
    15.426815967079921,
    17.850526684184697,
    20.65502716715848,
    23.90014338647177,
    27.655100585011382,
    32.0,
)

N_MARBLES = 25
ENSEMBLE_SPREAD = 0.5
N_CHANGED = 5
ENSEMBLE_CHANGE = 1.4


def scaled_gaussian_quantiles(n: int = N_MARBLES) -> np.ndarray:
    """Return standardized Gaussian quantiles.

    Sample the inverse normal CDF at i/(n+1), for i=1..n, and standardize
    the values to mean 0 and standard deviation 1.
    """

    probabilities = np.arange(1, n + 1, dtype=float) / (n + 1)
    values = stats.norm.ppf(probabilities)
    return (values - np.mean(values)) / np.std(values)


def ensemble_masses(
    center_mass: float,
    spread: float = ENSEMBLE_SPREAD,
    n: int = N_MARBLES,
) -> list[float]:
    """Generate the ordered log-normal mass vector for one baseline ensemble."""

    z_values = scaled_gaussian_quantiles(n)
    log_scale = math.log1p(spread)
    return [math.exp(math.log(center_mass) + log_scale * z) for z in z_values]


def geometric_mean(values: list[float]) -> float:
    return math.exp(math.fsum(math.log(float(value)) for value in values) / len(values))


def comparison_parameters(
    parameters: list[dict[str, Any]],
    condition: str,
    ensemble_change: float = ENSEMBLE_CHANGE,
    n_changed: int = N_CHANGED,
) -> list[dict[str, Any]]:
    """Reproduce the exact Experiment 2 heavier/lighter JSON transformation.

    To make the ensemble geometric mean change by ``ensemble_change`` while
    altering k of N marbles, every selected marble must change by
    ``ensemble_change ** (N/k)``.  The heavier condition changes the five
    lightest marbles; the lighter condition changes the five heaviest.
    """

    if condition not in {"heavier", "lighter"}:
        raise ValueError("condition must be 'heavier' or 'lighter'")
    if not 0 < n_changed <= len(parameters):
        raise ValueError("n_changed must be between 1 and the ensemble size")

    items = copy.deepcopy(parameters)
    reverse = condition == "lighter"
    ordered = sorted(items, key=lambda item: item["mass"], reverse=reverse)
    selected = ordered[:n_changed]
    remaining = ordered[n_changed:]
    exponent = len(items) / n_changed
    scale = ensemble_change**exponent
    if condition == "lighter":
        scale = (1 / ensemble_change) ** exponent

    for item in selected:
        item["mass_original"] = item["mass"]
        item["mass"] *= scale
    return remaining + selected


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_archive(root: Path = ROOT) -> dict[str, Any]:
    """Check the mass formulas against every retained paper stimulus JSON."""

    exp1 = root / "parameters" / "experiment1" / "ensemble"
    exp2 = root / "parameters" / "experiment2"
    normal_paths = sorted(exp1.rglob("*.json"))
    if len(normal_paths) != 78:
        raise ValueError(f"expected 78 baseline ensemble JSONs, found {len(normal_paths)}")

    centers: set[float] = set()
    max_mass_error = 0.0
    comparisons_checked = 0
    for exp1_path in normal_paths:
        relative = exp1_path.relative_to(exp1)
        parameters = load_json(exp1_path)
        if not isinstance(parameters, list) or len(parameters) != N_MARBLES:
            raise ValueError(f"{relative.as_posix()} is not a {N_MARBLES}-marble JSON")

        observed = sorted(float(item["mass"]) for item in parameters)
        center = observed[N_MARBLES // 2]
        centers.add(center)
        expected = ensemble_masses(center)
        error = max(abs(actual - designed) for actual, designed in zip(observed, expected))
        max_mass_error = max(max_mass_error, error)
        if not np.allclose(observed, expected, rtol=1e-13, atol=1e-13):
            raise ValueError(
                f"{relative.as_posix()} does not match the Gaussian-quantile mass design "
                f"(maximum absolute error {error})"
            )

        exp2_normal_path = exp2 / "normal" / relative
        if exp1_path.read_bytes() != exp2_normal_path.read_bytes():
            raise ValueError(f"Experiment 2 normal JSON differs from Experiment 1: {relative}")

        exp2_parameters = load_json(exp2_normal_path)
        for condition in ("heavier", "lighter"):
            expected_comparison = comparison_parameters(exp2_parameters, condition)
            observed_comparison = load_json(exp2 / condition / relative)
            if observed_comparison != expected_comparison:
                raise ValueError(
                    f"Experiment 2 {condition} JSON does not match the recorded transformation: "
                    f"{relative.as_posix()}"
                )
            comparisons_checked += 1

    if len(centers) != len(MASS_LEVELS) or not np.allclose(
        sorted(centers), MASS_LEVELS, rtol=1e-13, atol=1e-13
    ):
        raise ValueError("retained ensemble JSONs do not cover the 21 designed mass levels")

    reference = ensemble_masses(REFERENCE_MASS)
    return {
        "baseline_jsons": len(normal_paths),
        "comparison_jsons": comparisons_checked,
        "mass_levels": len(centers),
        "marbles_per_ensemble": N_MARBLES,
        "reference_mass": REFERENCE_MASS,
        "reference_geometric_mean": geometric_mean(reference),
        "reference_min_ratio": min(reference) / REFERENCE_MASS,
        "reference_max_ratio": max(reference) / REFERENCE_MASS,
        "changed_marbles": N_CHANGED,
        "heavier_marble_multiplier": ENSEMBLE_CHANGE ** (N_MARBLES / N_CHANGED),
        "lighter_marble_multiplier": (1 / ENSEMBLE_CHANGE) ** (N_MARBLES / N_CHANGED),
        "ensemble_geometric_mean_multiplier": ENSEMBLE_CHANGE,
        "max_baseline_mass_error": max_mass_error,
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="print one designed mass vector")
    show.add_argument("--center", type=float, default=REFERENCE_MASS)
    subparsers.add_parser("check", help="check every retained JSON against the design")
    args = parser.parse_args()

    if args.command == "show":
        masses = ensemble_masses(args.center)
        print(
            json.dumps(
                {
                    "center_mass": args.center,
                    "geometric_mean": geometric_mean(masses),
                    "masses": masses,
                },
                indent=2,
            )
        )
        return 0

    print(json.dumps(validate_archive(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
