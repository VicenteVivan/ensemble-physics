#!/usr/bin/env python3
"""Generate seeded stimulus parameters and save them under generated/."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from mass_design import comparison_parameters, ensemble_masses, geometric_mean


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "generation_config.json"
RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
OBJECT_KEYS = ("x", "z", "mass", "height", "rx", "ry", "rz")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=4, ensure_ascii=False) + "\n").encode("utf-8")


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("generation config must use schema_version 1")
    positions = config.get("grid_positions", [])
    ensemble = config.get("ensemble", {})
    if len(positions) != int(ensemble.get("objects", 0)):
        raise ValueError("grid_positions must match ensemble.objects")
    if any(not isinstance(position, list) or len(position) != 2 for position in positions):
        raise ValueError("every grid position must be an [x, z] pair")
    mass_levels = config.get("mass_levels", [])
    if not mass_levels or any(float(mass) <= 0 for mass in mass_levels):
        raise ValueError("all mass levels must be positive")
    if float(config.get("reference_mass", 0)) <= 0:
        raise ValueError("reference_mass must be positive")
    low, high = config.get("height_range", [0, 0])
    if not float(low) < float(high):
        raise ValueError("height_range must increase")
    low, high = config.get("rotation_range", [0, 0])
    if not float(low) < float(high):
        raise ValueError("rotation_range must increase")
    if float(config.get("position_jitter", -1)) < 0:
        raise ValueError("position_jitter cannot be negative")
    if float(ensemble.get("spread", -1)) < 0:
        raise ValueError("ensemble.spread cannot be negative")
    changed = int(config.get("experiment2", {}).get("changed_objects", 0))
    if not 0 < changed <= len(positions):
        raise ValueError("experiment2.changed_objects must be within the ensemble size")
    if float(config.get("experiment2", {}).get("ensemble_change", 0)) <= 0:
        raise ValueError("experiment2.ensemble_change must be positive")


def mass_token(mass: float) -> int:
    """Return the filename token (8.0 -> 80)."""

    return int(float(mass) * 10)


def selected_masses(
    config: dict[str, Any], requested: list[float] | None, all_masses: bool
) -> list[float]:
    if requested and all_masses:
        raise ValueError("use either --mass or --all-masses, not both")
    masses = (
        [float(value) for value in config["mass_levels"]]
        if all_masses
        else [float(value) for value in requested]
        if requested
        else [float(config["reference_mass"])]
    )
    if any(mass <= 0 for mass in masses):
        raise ValueError("mass values must be positive")
    tokens = [mass_token(mass) for mass in masses]
    if len(tokens) != len(set(tokens)):
        raise ValueError("mass values must have distinct filename tokens")
    return masses


def sampled_object(
    rng: random.Random,
    position: list[float],
    mass: float,
    config: dict[str, Any],
) -> dict[str, float]:
    jitter = float(config["position_jitter"])
    height_low, height_high = (float(value) for value in config["height_range"])
    rotation_low, rotation_high = (float(value) for value in config["rotation_range"])
    return {
        "x": float(position[0]) + rng.uniform(-jitter, jitter),
        "z": float(position[1]) + rng.uniform(-jitter, jitter),
        "mass": float(mass),
        "height": rng.uniform(height_low, height_high),
        "rx": rng.uniform(rotation_low, rotation_high),
        "ry": rng.uniform(rotation_low, rotation_high),
        "rz": rng.uniform(rotation_low, rotation_high),
    }


def generate_single(
    rng: random.Random, mass: float, config: dict[str, Any]
) -> list[dict[str, float]]:
    position = rng.choice(config["grid_positions"])
    return [sampled_object(rng, position, mass, config)]


def generate_ensemble(
    rng: random.Random, mass: float, config: dict[str, Any]
) -> list[dict[str, float]]:
    ensemble = config["ensemble"]
    masses = ensemble_masses(
        mass,
        spread=float(ensemble["spread"]),
        n=int(ensemble["objects"]),
    )
    rng.shuffle(masses)
    return [
        sampled_object(rng, position, object_mass, config)
        for position, object_mass in zip(config["grid_positions"], masses)
    ]


def build_parameter_files(
    kind: str,
    config: dict[str, Any],
    seed: int,
    masses: list[float],
    variations: int,
    variation_start: int,
) -> tuple[dict[Path, bytes], list[dict[str, Any]]]:
    if kind not in {"single", "ensemble", "experiment2"}:
        raise ValueError(f"unsupported generation kind: {kind}")
    if variations < 1:
        raise ValueError("variations must be at least 1")
    if variation_start < 0:
        raise ValueError("variation start cannot be negative")

    rng = random.Random(seed)
    outputs: dict[Path, bytes] = {}
    records: list[dict[str, Any]] = []
    spread_index = int(config["ensemble"]["spread_index"])
    experiment2 = config["experiment2"]

    for variation in range(variation_start, variation_start + variations):
        for mass in masses:
            token = mass_token(mass)
            directory = Path(f"mass_{token}")
            if kind == "single":
                parameters = generate_single(rng, mass, config)
                relative = Path("single") / directory / f"m{token}_v{variation}.json"
                variants = [(relative, "single", parameters)]
            else:
                parameters = generate_ensemble(rng, mass, config)
                filename = f"m{token}_s{spread_index}_v{variation}.json"
                if kind == "ensemble":
                    variants = [(Path("ensemble") / directory / filename, "normal", parameters)]
                else:
                    variants = [(Path("experiment2") / "normal" / directory / filename, "normal", parameters)]
                    for condition in ("heavier", "lighter"):
                        changed = comparison_parameters(
                            parameters,
                            condition,
                            ensemble_change=float(experiment2["ensemble_change"]),
                            n_changed=int(experiment2["changed_objects"]),
                        )
                        variants.append(
                            (
                                Path("experiment2") / condition / directory / filename,
                                condition,
                                changed,
                            )
                        )

            for relative, condition, objects in variants:
                data = json_bytes(objects)
                if relative in outputs:
                    raise ValueError(f"duplicate generated path: {relative.as_posix()}")
                outputs[relative] = data
                records.append(
                    {
                        "path": relative.as_posix(),
                        "sha256": sha256_bytes(data),
                        "objects": len(objects),
                        "condition": condition,
                        "target_mass": mass,
                        "geometric_mean": geometric_mean(
                            [float(item["mass"]) for item in objects]
                        ),
                    }
                )
    return outputs, records


def build_manifest(
    kind: str,
    config_path: Path,
    config: dict[str, Any],
    seed: int,
    masses: list[float],
    variations: int,
    variation_start: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "classification": "seeded stimulus parameters",
        "kind": kind,
        "seed": seed,
        "settings": {
            "masses": masses,
            "variations": variations,
            "variation_start": variation_start,
            "grid_positions": config["grid_positions"],
            "position_jitter": config["position_jitter"],
            "height_range": config["height_range"],
            "rotation_range": config["rotation_range"],
            "ensemble": config["ensemble"],
            "experiment2": config["experiment2"],
        },
        "rng": {
            "implementation": "python.random.Random (MT19937)",
            "python_version": sys.version.split()[0],
        },
        "generator_sha256": sha256_file(Path(__file__)),
        "config": {
            "filename": config_path.name,
            "sha256": sha256_file(config_path),
        },
        "files": records,
    }


def write_run(output: Path, files: dict[Path, bytes], manifest: dict[str, Any]) -> str:
    expected = dict(files)
    expected[Path("generation_manifest.json")] = json_bytes(manifest)
    if output.exists():
        actual_paths = {
            path.relative_to(output)
            for path in output.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        if actual_paths == set(expected) and all(
            (output / relative).read_bytes() == data for relative, data in expected.items()
        ):
            return "unchanged"
        raise FileExistsError(
            f"{output} already exists with different contents; choose another --name or --output"
        )

    for relative, data in expected.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return "created"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def safe_output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    if not relative.parts or relative.parts[0] != "generated":
        raise ValueError("repository-local output must be beneath stimuli/generated/")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("single", "ensemble", "experiment2"))
    parser.add_argument("--seed", type=int, required=True, help="required reproducible random seed")
    parser.add_argument("--name", help="run folder name; defaults to KIND-seed-SEED")
    parser.add_argument("--mass", type=float, action="append", help="target mass; may be repeated")
    parser.add_argument("--all-masses", action="store_true", help="use all configured mass levels")
    parser.add_argument("--variations", type=int, help="variations per target mass")
    parser.add_argument("--start", type=int, help="first variation number")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--output",
        type=Path,
        help="explicit folder outside the repository or beneath stimuli/generated",
    )
    args = parser.parse_args()

    config_path = args.config.expanduser().resolve()
    try:
        config = load_config(config_path)
        masses = selected_masses(config, args.mass, args.all_masses)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    variations = (
        args.variations
        if args.variations is not None
        else int(config["default_variations"])
    )
    variation_start = (
        args.start if args.start is not None else int(config["default_variation_start"])
    )
    run_name = args.name or f"{args.kind}-seed-{args.seed}"
    if not RUN_NAME.fullmatch(run_name):
        raise SystemExit("--name may contain only letters, numbers, dots, dashes, and underscores")
    try:
        output = safe_output_path(
            args.output if args.output else ROOT / "generated" / "parameters" / run_name
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        files, records = build_parameter_files(
            args.kind,
            config,
            args.seed,
            masses,
            variations,
            variation_start,
        )
        manifest = build_manifest(
            args.kind,
            config_path,
            config,
            args.seed,
            masses,
            variations,
            variation_start,
            records,
        )
        status = write_run(output, files, manifest)
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(
        json.dumps(
            {
                "status": status,
                "kind": args.kind,
                "seed": args.seed,
                "output": display_path(output),
                "json_files": len(files),
                "manifest": display_path(output / "generation_manifest.json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
