"""Trial selection, adaptive sampling, and scoring for Experiment 1."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import numpy as np


APP_ROOT = Path(__file__).resolve().parent
SOURCE_COMMIT = "e18952d0eb71b8f9c92a215c4b25fce1a1033ec8"
N_ADAPTIVE_TRIALS = 57
N_CATCH_TRIALS = 3
TOTAL_TRIALS = 60
CATCH_RANDOM_INTERVAL = 3
REWARD_INTERVAL = 10
REFERENCE_MASS = 8.0

MASSES = [
    2.0000,
    2.3142,
    2.6778,
    3.0985,
    3.5853,
    4.1486,
    4.8004,
    5.5546,
    6.4272,
    7.4370,
    8.0000,
    8.6055,
    9.9575,
    11.521,
    13.332,
    15.426,
    17.850,
    20.655,
    23.900,
    27.655,
    32.0,
]

VIDEO_ROOTS = {
    "single": Path("static/videos_single"),
    "multi": Path("static/videos_multi"),
}


def load_manifest():
    with (APP_ROOT / "protocol_manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def one(fields, key, default=""):
    values = fields.get(key, [default])
    return values[0] if values else default


def query_value(parameters, key, default=""):
    return one(parameters, key, default)


def video_directory(section, mass):
    return APP_ROOT / VIDEO_ROOTS[section] / f"mass_{int(mass * 10)}"


def video_url(path):
    return path.relative_to(APP_ROOT).as_posix()


def videos_for_mass(section, mass):
    directory = video_directory(section, mass)
    if not directory.is_dir():
        raise FileNotFoundError(f"Missing stimulus directory: {VIDEO_ROOTS[section] / directory.name}")
    videos = [directory / name for name in os.listdir(directory) if name.endswith(".mp4")]
    if not videos:
        raise FileNotFoundError(f"No MP4 stimuli in: {VIDEO_ROOTS[section] / directory.name}")
    return [video_url(path) for path in videos]


def place_catch_trials(n, m, rand_range, np_random=None):
    """Place catch trials within the specified trial intervals."""

    np_random = np.random if np_random is None else np_random
    buffer_size = min(max(2, n // 10), (n - m) // 2)
    effective_trials = n - 2 * buffer_size
    spacing = effective_trials / (m + 1)
    catch_positions = set()
    positions = []

    for index in range(m):
        position = int(buffer_size + (index + 1) * spacing)
        adjustments = np.arange(-rand_range, rand_range + 1)
        np_random.shuffle(adjustments)
        for adjustment in adjustments:
            adjusted = int(position + adjustment)
            adjusted = max(min(adjusted, n - buffer_size - 1), buffer_size + 1)
            if adjusted not in catch_positions:
                catch_positions.add(adjusted)
                positions.append(adjusted)
                break
        else:
            raise ValueError(f"Cannot place catch trial {index + 1}")
    return sorted(positions)


def check_understanding(fields):
    return one(fields, "question1") == "C" and one(fields, "question2") == "D"


def response_label(choice, default_first=True):
    value = int(choice)
    labels = ["Lighter", "Heavier"] if default_first else ["Heavier", "Lighter"]
    return labels[value]


def is_response_correct(response, mass):
    if mass > REFERENCE_MASS:
        return response == "Heavier"
    if mass < REFERENCE_MASS:
        return response == "Lighter"
    return True


class QuestPlusCustomMixin:
    """Select the next stimulus from the QUEST+ estimates."""

    def next_stim_pair(self):
        new_posterior = self.posterior * self.likelihoods
        probability = new_posterior.sum(dim=self.param_domain.keys())
        new_posterior /= probability
        with np.errstate(divide="ignore"):
            entropy = -(new_posterior * np.log(new_posterior)).sum(dim=self.param_domain.keys())
        expected_entropy = (probability * entropy).sum(dim=list(self.outcome_domain.keys()))
        sorted_indices = np.unravel_index(expected_entropy.argsort(), expected_entropy.shape)[0]
        mean_intensity = np.mean(self.stim_domain["intensity"])
        below = above = optimal = None
        for index in sorted_indices:
            stimulus = {dimension: expected_entropy[dimension][index].item() for dimension in self.stim_domain}
            intensity = stimulus["intensity"]
            optimal = stimulus if optimal is None else optimal
            below = stimulus if below is None and intensity < mean_intensity else below
            above = stimulus if above is None and intensity > mean_intensity else above
            if below is not None and above is not None:
                break
        if below is None or above is None:
            raise ValueError("Could not find stimuli above and below the domain mean")
        return {"lighter": below, "heavier": above, "optimal": optimal}


class QuestStaircase:
    """Adaptive staircase using QUEST+ 2023.1."""

    def __init__(self, rng=None):
        try:
            import questplus as qp
        except ImportError as exc:
            raise RuntimeError("Install requirements.txt to run the adaptive experiment") from exc

        self.qp = qp
        self.rng = random if rng is None else rng
        self.log_masses = np.log(MASSES)
        custom_class = type("QuestPlusCustom", (QuestPlusCustomMixin, qp.QuestPlus), {})
        self.q = custom_class(
            stim_domain={"intensity": self.log_masses},
            param_domain={
                "mean": self.log_masses.copy(),
                "sd": np.linspace(0.01, 2.0, 30),
                "lapse_rate": np.linspace(0, 0.2, 10),
            },
            outcome_domain={"response": ["Heavier", "Lighter"]},
            func="norm_cdf_2",
            stim_scale="linear",
            stim_selection_method="min_entropy",
            param_estimation_method="mean",
            stim_selection_options={"max_consecutive_reps": 2, "n": 3},
        )

    def next_stimulus(self, section):
        stimulus = self.q.next_stim_pair()["optimal"]
        mass = float(np.exp(stimulus["intensity"]))
        mass = min(MASSES, key=lambda candidate: abs(candidate - mass))
        return {"mass": mass, "video": self.rng.choice(videos_for_mass(section, mass))}

    def update(self, stimulus, response):
        self.q.update(
            stim={"intensity": np.log(stimulus["mass"])},
            outcome={"response": response},
        )

    def get_fit_details(self):
        from scipy.optimize import fsolve

        params = self.q.param_estimate

        def solve_threshold(probability):
            def objective(intensity):
                value = self.qp.psychometric_function.norm_cdf_2(
                    intensity=intensity,
                    mean=params["mean"],
                    sd=params["sd"],
                    lapse_rate=params["lapse_rate"],
                    scale="linear",
                )
                return value.item() - probability

            threshold, = fsolve(objective, x0=params["mean"])
            return float(np.exp(threshold) / REFERENCE_MASS)

        return {
            "params": {key: float(value) for key, value in params.items()},
            "thresholds": [solve_threshold(probability) for probability in (0.25, 0.50, 0.75)],
        }


def inventory_summary():
    return {
        section: {
            "files": sum(len(videos_for_mass(section, mass)) for mass in MASSES),
            "mass_folders": len(MASSES),
        }
        for section in VIDEO_ROOTS
    }

