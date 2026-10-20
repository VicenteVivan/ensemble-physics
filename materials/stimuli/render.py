#!/usr/bin/env python3
"""Render videos from the saved stimulus parameters."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_project() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def dataset(project: dict, name: str) -> dict:
    try:
        item = dict(project["datasets"][name])
    except KeyError:
        available = ", ".join(sorted(project["datasets"]))
        raise SystemExit(f"Unknown dataset {name!r}. Available: {available}")

    scene = dict(project["scenes"][item["scene"]])
    item.update(
        name=name,
        scene_path=(ROOT / scene["path"]).resolve(),
        parameter_bridge=scene["parameter_bridge"],
        parameters_path=(ROOT / item["parameters"]).resolve(),
        videos_path=(ROOT / item["videos"]).resolve(),
    )
    return item


def parameter_files(item: dict, pattern: str | None = None) -> list[Path]:
    files = sorted(
        path
        for path in item["parameters_path"].rglob("*.json")
        if path.name != "generation_manifest.json"
    )
    if pattern:
        files = [
            path
            for path in files
            if fnmatch.fnmatch(path.relative_to(item["parameters_path"]).as_posix(), pattern)
            or fnmatch.fnmatch(path.stem, pattern)
        ]
    expected = item.get("expected_trials")
    if pattern is None and expected is not None and len(files) != expected:
        raise SystemExit(
            f"{item['name']} has {len(files)} parameter files; expected {expected}."
        )
    return files


def read_balls(path: Path, bridge: str) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        balls = json.load(handle)
    if not isinstance(balls, list) or not balls:
        raise SystemExit(f"Parameter file must contain a non-empty list: {path}")
    expected_count = 1 if bridge == "objects_single" else 25
    if len(balls) != expected_count:
        raise SystemExit(
            f"{path} contains {len(balls)} objects; expected {expected_count}."
        )
    required = {"x", "z", "mass", "height"}
    if bridge == "objects":
        required |= {"rx", "ry", "rz"}
    for index, ball in enumerate(balls, start=1):
        missing = sorted(required - set(ball))
        if missing:
            raise SystemExit(f"{path}, object {index}, is missing: {', '.join(missing)}")
    return balls


def video_for(item: dict, parameter_path: Path) -> Path:
    relative = parameter_path.relative_to(item["parameters_path"]).with_suffix(".mp4")
    return item["videos_path"] / relative


def resolve_trial(item: dict, selector: str) -> Path:
    candidates = parameter_files(item)
    normalized = selector[:-5] if selector.endswith(".json") else selector
    exact = [
        path
        for path in candidates
        if path.relative_to(item["parameters_path"]).with_suffix("").as_posix()
        == normalized
    ]
    if not exact:
        exact = [path for path in candidates if path.stem == normalized]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        matches = ", ".join(
            path.relative_to(item["parameters_path"]).as_posix() for path in exact
        )
        raise SystemExit(f"Ambiguous trial {selector!r}: {matches}")
    raise SystemExit(f"No trial {selector!r} in {item['name']}.")


def find_hython() -> str:
    candidates: list[Path] = []
    on_path = shutil.which("hython")
    if on_path:
        candidates.append(Path(on_path))
    candidates.append(
        Path(
            "/Applications/Houdini/Current/Frameworks/Houdini.framework/"
            "Versions/Current/Resources/bin/hython"
        )
    )
    candidates.extend(
        sorted(
            Path("/Applications/Houdini").glob(
                "Houdini*/Frameworks/Houdini.framework/Versions/*/Resources/bin/hython"
            ),
            reverse=True,
        )
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise SystemExit("Could not find hython. Install Houdini or put hython on PATH.")


def write_parameter_bridge(stage: Path, bridge: str, balls: list[dict]) -> None:
    bridge_dir = stage / bridge
    bridge_dir.mkdir(parents=True, exist_ok=True)
    for index, ball in enumerate(balls, start=1):
        values = [ball["x"], ball["z"], ball["mass"], ball["height"]]
        if bridge == "objects":
            values.extend([ball["rx"], ball["ry"], ball["rz"]])
            output = bridge_dir / f"params_{index}.txt"
        else:
            output = bridge_dir / "params.txt"
        output.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


def run_hython(job: dict, source_scene: Path, bridge: str, balls: list[dict]) -> None:
    with tempfile.TemporaryDirectory(prefix="things-stuff-render-") as temporary:
        stage = Path(temporary)
        staged_scene = stage / source_scene.name
        shutil.copy2(source_scene, staged_scene)
        write_parameter_bridge(stage, bridge, balls)
        job["scene"] = str(staged_scene)
        job_path = stage / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        result = subprocess.run(
            [find_hython(), str(Path(__file__).resolve()), "_hython", str(job_path)],
        )
        if result.returncode:
            raise SystemExit(
                "Houdini could not complete the render. If it reported that no "
                "licenses were found, open SideFX License Administrator, sign in, "
                "and install or renew the free Apprentice license."
            )


def make_video(template: Path, fps: int, start_frame: int) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found; rendered frames were left in place.")
    if "$F4" not in str(template):
        raise SystemExit("A frame-range output template must contain '$F4'.")
    video = Path(str(template).replace(".$F4.jpg", ".mp4"))
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-start_number",
            str(start_frame),
            "-i",
            str(template).replace("$F4", "%04d"),
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


def frame_range(project: dict, args: argparse.Namespace) -> list[int]:
    if args.frame is not None:
        return [args.frame, args.frame]
    if args.range is not None:
        return list(args.range)
    return list(project["render"]["frame_range"])


def default_output(item: dict, parameter_path: Path, frames: list[int]) -> Path:
    relative = parameter_path.relative_to(item["parameters_path"])
    if "output_group" in item:
        base = (
            ROOT
            / "generated"
            / "renders"
            / item["output_group"]
            / relative.parent
            / relative.stem
        )
    else:
        base = ROOT / "generated" / item["name"] / relative.parent / relative.stem
    if frames[0] == frames[1]:
        return base / f"{relative.stem}.frame-{frames[0]}.jpg"
    return base / f"{relative.stem}.$F4.jpg"


def render_one(
    project: dict,
    item: dict,
    parameter_path: Path,
    args: argparse.Namespace,
) -> None:
    balls = read_balls(parameter_path, item["parameter_bridge"])
    frames = frame_range(project, args)
    output = (
        (ROOT / args.output).resolve()
        if args.output and not Path(args.output).is_absolute()
        else Path(args.output).resolve()
        if args.output
        else default_output(item, parameter_path, frames)
    )
    if frames[0] != frames[1] and "$F4" not in str(output):
        raise SystemExit("A frame-range output must contain '$F4'.")

    relative = parameter_path.relative_to(item["parameters_path"]).as_posix()
    summary = {
        "dataset": item["name"],
        "trial": relative,
        "scene": item["scene_path"].relative_to(ROOT).as_posix(),
        "objects": len(balls),
        "frames": frames,
        "output": str(output),
        "video": args.video,
    }
    print(json.dumps(summary, sort_keys=True))
    if args.dry_run:
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    assets = {
        name: str((ROOT / relative_path).resolve())
        for name, relative_path in project["assets"].items()
    }
    run_hython(
        {
            "render_node": project["render"]["render_node"],
            "frames": frames,
            "output": str(output),
            "resolution": args.resolution,
            "assets": assets,
        },
        item["scene_path"],
        item["parameter_bridge"],
        balls,
    )
    if args.video and frames[0] != frames[1]:
        print(make_video(output, project["render"]["fps"], frames[0]))


def command_list(args: argparse.Namespace) -> None:
    project = load_project()
    item = dataset(project, args.dataset)
    files = parameter_files(item, args.match)
    if args.limit:
        files = files[: args.limit]
    for index, path in enumerate(files, start=1):
        balls = read_balls(path, item["parameter_bridge"])
        video = video_for(item, path)
        result = {
            "index": index,
            "trial": path.relative_to(item["parameters_path"]).as_posix(),
            "objects": len(balls),
            "video": video.relative_to(ROOT.parent).as_posix(),
            "video_exists": video.is_file(),
        }
        if args.details:
            result["balls"] = balls
        print(json.dumps(result, sort_keys=True))


def command_render(args: argparse.Namespace) -> None:
    project = load_project()
    item = dataset(project, args.dataset)
    render_one(project, item, resolve_trial(item, args.trial), args)


def command_batch(args: argparse.Namespace) -> None:
    project = load_project()
    item = dataset(project, args.dataset)
    files = parameter_files(item, args.match)
    if args.limit:
        files = files[: args.limit]
    for path in files:
        render_one(project, item, path, args)


def input_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def file_item(project: dict, scene_name: str, parameters_path: Path) -> dict:
    try:
        scene = project["scenes"][scene_name]
    except KeyError as exc:
        available = ", ".join(sorted(project["scenes"]))
        raise SystemExit(f"Unknown scene {scene_name!r}. Available: {available}") from exc
    generated_root = ROOT / "generated" / "parameters"
    try:
        output_group = parameters_path.resolve().relative_to(generated_root)
    except ValueError:
        resolved = parameters_path.resolve()
        digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:10]
        output_group = Path(f"external-{scene_name}-{resolved.name}-{digest}")
    return {
        "name": f"generated-{scene_name}",
        "output_group": output_group,
        "scene_path": (ROOT / scene["path"]).resolve(),
        "parameter_bridge": scene["parameter_bridge"],
        "parameters_path": parameters_path.resolve(),
    }


def command_render_file(args: argparse.Namespace) -> None:
    project = load_project()
    path = input_path(args.parameter_file)
    if not path.is_file() or path.suffix.lower() != ".json":
        raise SystemExit(f"Parameter JSON was not found: {path}")
    item = file_item(project, args.scene, path.parent)
    render_one(project, item, path, args)


def command_batch_files(args: argparse.Namespace) -> None:
    project = load_project()
    directory = input_path(args.directory)
    if not directory.is_dir():
        raise SystemExit(f"Parameter directory was not found: {directory}")
    item = file_item(project, args.scene, directory)
    files = parameter_files(item, args.match)
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"No parameter JSON files found beneath {directory}")
    for path in files:
        render_one(project, item, path, args)


def _hython(job_path: str) -> None:
    import hou

    with open(job_path, encoding="utf-8") as handle:
        job = json.load(handle)

    stage = str(Path(job["scene"]).parent)
    hou.putenv("HIP", stage)
    hou.putenv("JOB", stage)
    hou.hipFile.load(job["scene"], suppress_save_prompt=True, ignore_load_warnings=True)
    # Houdini restores the scene's saved HIP/JOB metadata while loading. Point
    # both special variables back to the temporary, portable runtime stage.
    hou.putenv("HIP", stage)
    hou.putenv("JOB", stage)

    # Resolve scene texture paths to the bundled assets by filename.
    for node in hou.node("/").allSubChildren():
        for parm in node.parms():
            try:
                raw = parm.unexpandedString()
            except (hou.OperationFailed, hou.PermissionError):
                continue
            for basename, replacement in job["assets"].items():
                if basename in raw:
                    try:
                        parm.set(replacement)
                    except hou.PermissionError:
                        pass
                    break

    rop = hou.node(job["render_node"])
    if rop is None:
        raise RuntimeError(f"Missing render node {job['render_node']}")
    rop.parm("vm_picture").set(job["output"])

    if job.get("resolution"):
        width, height = job["resolution"]
        if rop.parm("override_camerares"):
            rop.parm("override_camerares").set(1)
        if rop.parm("res_fraction"):
            rop.parm("res_fraction").set("specific")
        if rop.parm("res_overridex"):
            rop.parm("res_overridex").set(width)
        if rop.parm("res_overridey"):
            rop.parm("res_overridey").set(height)

    start, end = job["frames"]
    hou.setFrame(start)
    rop.render(frame_range=(start, end), verbose=True)


def add_render_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frame", type=int, help="render one preview frame")
    parser.add_argument("--range", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--resolution", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--output", help="project-relative frame path/template")
    parser.add_argument("--video", action="store_true", help="encode rendered frames")
    parser.add_argument("--dry-run", action="store_true", help="validate without Houdini")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list exact recorded trials")
    list_parser.add_argument("dataset")
    list_parser.add_argument("--match", help="glob against a relative path or stem")
    list_parser.add_argument("--limit", type=int)
    list_parser.add_argument("--details", action="store_true")

    render_parser = subparsers.add_parser("render", help="render one recorded trial")
    render_parser.add_argument("dataset")
    render_parser.add_argument("trial", help="relative JSON path or unique trial stem")
    add_render_flags(render_parser)

    batch_parser = subparsers.add_parser("batch", help="render recorded trials")
    batch_parser.add_argument("dataset")
    batch_parser.add_argument("--match", help="glob against a relative path or stem")
    batch_parser.add_argument("--limit", type=int)
    add_render_flags(batch_parser)

    render_file_parser = subparsers.add_parser(
        "render-file", help="render one generated or external parameter JSON"
    )
    render_file_parser.add_argument("scene", choices=("single", "ensemble"))
    render_file_parser.add_argument("parameter_file")
    add_render_flags(render_file_parser)

    batch_files_parser = subparsers.add_parser(
        "batch-files", help="render generated or external parameter JSONs"
    )
    batch_files_parser.add_argument("scene", choices=("single", "ensemble"))
    batch_files_parser.add_argument("directory")
    batch_files_parser.add_argument("--match", help="glob against a relative path or stem")
    batch_files_parser.add_argument("--limit", type=int)
    add_render_flags(batch_files_parser)

    hython_parser = subparsers.add_parser("_hython")
    hython_parser.add_argument("job")

    args = parser.parse_args()
    if args.command == "list":
        command_list(args)
    elif args.command == "render":
        command_render(args)
    elif args.command == "batch":
        command_batch(args)
    elif args.command == "render-file":
        command_render_file(args)
    elif args.command == "batch-files":
        command_batch_files(args)
    elif args.command == "_hython":
        _hython(args.job)


if __name__ == "__main__":
    main()
