"""Trial selection and scoring for Experiment 2.

Condition, mass folder, clip, and presentation order are sampled independently
and uniformly.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import numpy as np


APP_ROOT = Path(__file__).resolve().parent
SOURCE_COMMIT = "01e1f9de6faaba0edb07f287df975cc541313162"
VIDEO_ROOT = Path("static/videos_multi")
PARAMETER_ROOT = Path("static/params_multi")

SECTION1_NORMAL_TRIALS = 55
SECTION1_CATCH_TRIALS = 5
SECTION1_TOTAL_TRIALS = 60
SECTION1_CATCH_INTERVAL = 5
SECTION2_NORMAL_TRIALS = 60
SECTION2_CATCH_TRIALS = 0
SECTION2_TOTAL_TRIALS = 60
REWARD_INTERVAL = 10


def one(fields, key, default=""):
    values = fields.get(key, [default])
    return values[0] if values else default


def load_manifest():
    with (APP_ROOT / "protocol_manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _url(path):
    return path.relative_to(APP_ROOT).as_posix()


def place_catch_trials(n, m, rand_range, np_random=None):
    """Place catch trials within the specified trial intervals."""

    np_random = np.random if np_random is None else np_random
    if m == 0:
        return []
    buffer_size = min(max(2, n // 10), (n - m) // 2)
    effective_trials = n - 2 * buffer_size
    spacing = effective_trials / (m + 1)
    used = set()
    positions = []
    for index in range(m):
        position = int(buffer_size + (index + 1) * spacing)
        adjustments = np.arange(-rand_range, rand_range + 1)
        np_random.shuffle(adjustments)
        for adjustment in adjustments:
            adjusted = int(position + adjustment)
            adjusted = max(min(adjusted, n - buffer_size - 1), buffer_size + 1)
            if adjusted not in used:
                used.add(adjusted)
                positions.append(adjusted)
                break
        else:
            raise ValueError(f"Cannot place catch trial {index + 1}")
    return sorted(positions)


def choose_video_pair(rng=None, root=None):
    """Select a matched baseline/comparison video pair."""

    rng = random if rng is None else rng
    root = APP_ROOT / VIDEO_ROOT if root is None else Path(root)
    comparison = rng.choice(["heavier", "lighter"])
    comparison_path = root / comparison
    normal_path = root / "normal"
    subfolders = [name for name in os.listdir(comparison_path) if (comparison_path / name).is_dir()]
    if not subfolders:
        raise FileNotFoundError(f"No mass folders in {comparison_path}")
    subfolder = rng.choice(subfolders)
    videos = [name for name in os.listdir(comparison_path / subfolder) if name.endswith(".mp4")]
    if not videos:
        raise FileNotFoundError(f"No MP4 stimuli in {comparison_path / subfolder}")
    filename = rng.choice(videos)
    comparison_video = comparison_path / subfolder / filename
    normal_video = normal_path / subfolder / filename
    if not normal_video.is_file():
        raise FileNotFoundError(f"Missing matched normal video: {normal_video}")

    if rng.choice([True, False]):
        video1, video2 = comparison_video, normal_video
        comparison_type = f"{comparison}-normal"
    else:
        video1, video2 = normal_video, comparison_video
        comparison_type = f"normal-{comparison}"
    return {
        "video1": _url(video1) if root == APP_ROOT / VIDEO_ROOT else video1.as_posix(),
        "video2": _url(video2) if root == APP_ROOT / VIDEO_ROOT else video2.as_posix(),
        "comparison_type": comparison_type,
        "is_catch": False,
    }


def catch_pair(kind):
    if kind == "light2heavy":
        return {
            "video1": "static/videos_multi/normal/mass_20/m20_s0_v3.mp4",
            "video2": "static/videos_multi/catch/m20_s0_v3.mp4",
            "comparison_type": "normal-heavier",
            "is_catch": True,
        }
    if kind == "heavy2light":
        return {
            "video1": "static/videos_multi/normal/mass_320/m320_s0_v3.mp4",
            "video2": "static/videos_multi/catch/m320_s0_v3.mp4",
            "comparison_type": "normal-lighter",
            "is_catch": True,
        }
    raise ValueError("Catch kind must be light2heavy or heavy2light")


def mass_code(video_path):
    """Calculate the mass values used by the response interface."""

    if "/catch/" in video_path:
        if "m320" in video_path:
            return -1
        if "m20" in video_path:
            return 1
    if "/heavier/" in video_path:
        return 1
    if "/lighter/" in video_path:
        return -1
    return 0


def mass_difference(pair):
    return mass_code(pair["video2"]) - mass_code(pair["video1"])


def group_choice_correct(pair, choice):
    difference = mass_difference(pair)
    return (difference > 0 and int(choice) == 1) or (difference < 0 and int(choice) == 0)


def individual_choice_correct(pair, choice, highlighted_changed):
    choice = int(choice)
    if not highlighted_changed:
        return choice == 1
    difference = mass_difference(pair)
    return (difference > 0 and choice == 2) or (difference < 0 and choice == 0)


def group_response_label(choice):
    value = int(choice)
    if value not in (0, 1):
        raise ValueError("Unknown group response")
    return ["Lighter", "Heavier"][value]


def individual_response_label(choice):
    value = int(choice)
    if value not in (0, 1, 2):
        raise ValueError("Unknown individual response")
    return ["Lighter", "Same", "Heavier"][value]


def parameter_url(pair):
    candidate = pair["video1"] if "/normal/" not in pair["video1"] else pair["video2"]
    if "/catch/" in candidate:
        filename = "m320_s0_v3.json" if "m320" in candidate else "m20_s0_v3.json"
        return f"static/params_multi/catch/{filename}"
    return candidate.replace("static/videos_multi/", "static/params_multi/").rsplit(".", 1)[0] + ".json"


def clean_coordinate(x, z):
    """Map Houdini positions to the 5x5 response grid."""

    x_values = [-2, -1, 0, 1, 2]
    z_values = [2, 1, 0, -1, -2]
    grid_size = 2 * (5 / 3)
    adjusted_x = x - (-2 / 3)
    adjusted_z = z - (2 / 3)

    def nearest(values, adjusted):
        return min(values, key=lambda value: abs(value * (grid_size / 5) - adjusted))

    return {"x": nearest(x_values, adjusted_x), "z": nearest(z_values, adjusted_z)}


def changed_coordinates(parameter_path):
    path = Path(parameter_path)
    if not path.is_absolute():
        path = APP_ROOT / path
    with path.open(encoding="utf-8") as handle:
        items = json.load(handle)
    if not isinstance(items, list) or len(items) != 25:
        raise ValueError("Incomplete stimulus parameters")
    if len({tuple(clean_coordinate(item['x'], item['z']).values()) for item in items}) != 25:
        raise ValueError("Stimulus grid locations are not unique")
    unique = {}
    for item in items:
        if "mass_original" in item:
            coordinate = clean_coordinate(item["x"], item["z"])
            unique[(coordinate["x"], coordinate["z"])] = coordinate
    expected = 15 if "catch" in path.parts else 5
    if len(unique) != expected:
        raise ValueError("Incomplete changed-location answer key")
    return list(unique.values())


def parse_grid_choice(raw_choice):
    choice = json.loads(raw_choice)
    if (not isinstance(choice, dict) or set(choice) != {"x", "z"}
            or any(type(choice[k]) is not int or not -2 <= choice[k] <= 2 for k in ('x', 'z'))):
        raise ValueError("Invalid grid coordinate")
    return choice


def grid_choice_correct(parameter_path, raw_choice):
    choice = parse_grid_choice(raw_choice)
    return any(
        choice.get("x") == coordinate["x"] and choice.get("z") == coordinate["z"]
        for coordinate in changed_coordinates(parameter_path)
    )


def check_understanding_section1(fields):
    return one(fields, "question1") == "C" and one(fields, "question2") == "D"


def check_understanding_section2(fields):
    return (
        one(fields, "question1") == "C"
        and one(fields, "question2") == "D"
        and one(fields, "question3") == "C"
    )


def inventory_summary():
    counts = {}
    for condition in ("normal", "heavier", "lighter", "catch"):
        base = APP_ROOT / VIDEO_ROOT / condition
        counts[condition] = sum(1 for path in base.rglob("*.mp4")) if base.is_dir() else 0
    counts["total"] = sum(counts.values())
    return counts
