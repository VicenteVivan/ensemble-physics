"""Run Experiment 1: single-marble and ensemble mass discrimination."""

from __future__ import annotations

import os
import random
from datetime import datetime, timezone

import pages
from kesar import kesar
from protocol import (
    CATCH_RANDOM_INTERVAL,
    N_ADAPTIVE_TRIALS,
    N_CATCH_TRIALS,
    REWARD_INTERVAL,
    SOURCE_COMMIT,
    TOTAL_TRIALS,
    QuestStaircase,
    check_understanding,
    is_response_correct,
    one,
    place_catch_trials,
    response_label,
    videos_for_mass,
)
from send_data import persist_data


EXPERIMENT_NAME = "things-vs-stuff-experiment-1"
EXPERIMENT_VERSION = "paper-protocol-ajax-1"
COMPLETION_URL = os.environ.get("PROLIFIC_COMPLETION_URL", "")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def flatten_query(parameters):
    return {
        key: (values[0] if values else "")
        for key, values in parameters.items()
        if not key.startswith("__")
    }


def prolific_metadata(parameters):
    return {
        key: one(parameters, key)
        for key in ("PROLIFIC_PID", "STUDY_ID", "SESSION_ID", "CONDITION")
    }


def eligible(fields):
    return all(one(fields, key) == "yes" for key in ("eighteen", "understood", "consent"))


def run_practice(section, rng):
    while True:
        yield pages.practice_intro_page()
        light = rng.choice(videos_for_mass(section, 2.0))
        heavy = rng.choice(videos_for_mass(section, 32.0))

        first = yield pages.trial_page("Practice (1/2)", light, heavy, section=section, practice=True)
        correct_first = response_label(one(first, "perception"), True) == "Heavier"

        second = yield pages.trial_page("Practice (2/2)", heavy, light, section=section, practice=True)
        correct_second = response_label(one(second, "perception"), True) == "Lighter"
        if correct_first and correct_second:
            return
        yield pages.practice_feedback_page()


def run_understanding_and_practice(section, section_number, rng):
    while True:
        response = yield pages.understanding_page()
        if check_understanding(response):
            break
        yield pages.retry_page()
        yield pages.section_instructions_page(section, section_number)
    yield from run_practice(section, rng)


def run_section(section, rng, staircase_factory=QuestStaircase):
    staircase = staircase_factory(rng=rng)
    default_videos = videos_for_mass(section, 8.0)
    light_videos = videos_for_mass(section, 2.0)
    heavy_videos = videos_for_mass(section, 32.0)
    catch_positions = set(
        place_catch_trials(N_ADAPTIVE_TRIALS, N_CATCH_TRIALS, CATCH_RANDOM_INTERVAL)
    )
    rows = {}
    total_points = 0
    interval_points = 0
    correct_catches = 0

    for index in range(TOTAL_TRIALS):
        if index in catch_positions:
            catch_heavier = rng.choice([True, False])
            light = rng.choice(light_videos)
            heavy = rng.choice(heavy_videos)
            video1, video2 = (light, heavy) if catch_heavier else (heavy, light)
            fields = yield pages.trial_page(
                f"({index + 1}/{TOTAL_TRIALS})", video1, video2, section=section
            )
            response = response_label(one(fields, "perception"), True)
            correct = (catch_heavier and response == "Heavier") or (
                not catch_heavier and response == "Lighter"
            )
            rows[f"catch_{index}"] = {
                "mass": "catch_heavier" if catch_heavier else "catch_lighter",
                "prediction": response,
                "order": index,
                "reaction_time": int(one(fields, "time", "0") or 0),
                "correct": correct,
            }
            if correct:
                correct_catches += 1
        else:
            default_video = rng.choice(default_videos)
            default_first = rng.choice([True, False])
            stimulus = staircase.next_stimulus(section)
            video1, video2 = (
                (default_video, stimulus["video"])
                if default_first
                else (stimulus["video"], default_video)
            )
            fields = yield pages.trial_page(
                f"({index + 1}/{TOTAL_TRIALS})", video1, video2, section=section
            )
            response = response_label(one(fields, "perception"), default_first)
            staircase.update(stimulus, response)
            world_name = stimulus["video"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            rows[f"{world_name}_{index}"] = {
                "mass": stimulus["mass"],
                "prediction": response,
                "order": index,
                "reaction_time": int(one(fields, "time", "0") or 0),
                "fit_details": staircase.get_fit_details(),
            }
            correct = is_response_correct(response, stimulus["mass"])

        if correct:
            total_points += 1
            interval_points += 1

        if (index + 1) % REWARD_INTERVAL == 0:
            yield pages.score_page(interval_points, REWARD_INTERVAL, total_points)
            interval_points = 0

    rows["fit_details"] = staircase.get_fit_details()
    return {"rows": rows, "points": total_points, "correct_catches": correct_catches}


def build_experiment(parameters, *, rng=None, staircase_factory=QuestStaircase):
    rng = random if rng is None else rng
    started = now_utc()
    prolific = prolific_metadata(parameters)
    data = {
        "single": {},
        "multi": {},
        "PROLIFIC_PID": prolific["PROLIFIC_PID"],
        "STUDY_ID": prolific["STUDY_ID"],
        "SESSION_ID": prolific["SESSION_ID"],
        "_experiment": {
            "name": EXPERIMENT_NAME,
            "version": EXPERIMENT_VERSION,
            "canonical_source_commit": SOURCE_COMMIT,
        },
        "_metadata": {
            "query": flatten_query(parameters),
            "prolific": prolific,
            "user_agent": one(parameters, "__user_agent__"),
            "started_at_utc": started,
            "completed_at_utc": None,
        },
        "_quality": {"excluded": False, "notes": []},
    }

    consent = yield pages.consent_page()
    if not eligible(consent):
        data["_quality"]["excluded"] = True
        data["_quality"]["notes"].append("participant_not_eligible_or_did_not_consent")
        data["_metadata"]["completed_at_utc"] = now_utc()
        result = persist_data(data)
        data["_persistence"] = result
        return data, pages.completion_page("", persistence_ok=result.get("ok", False))

    yield pages.general_instructions_page()
    single_first = rng.choice([True, False])
    order = ["single", "multi"] if single_first else ["multi", "single"]
    total_correct_catches = 0

    for section_number, section in enumerate(order, start=1):
        yield pages.section_instructions_page(section, section_number)
        if section_number == 1:
            yield from run_understanding_and_practice(section, section_number, rng)
        else:
            yield from run_practice(section, rng)
        yield pages.ready_page()
        result = yield from run_section(section, rng, staircase_factory=staircase_factory)
        data[section] = result["rows"]
        total_correct_catches += result["correct_catches"]

    data["stimuli_order"] = "single_first" if single_first else "multi_first"
    data["excluded"] = total_correct_catches < 5
    data["_quality"]["excluded"] = data["excluded"]
    if data["excluded"]:
        data["_quality"]["notes"].append("fewer_than_5_of_6_catch_trials_correct")
    data["_metadata"]["completed_at_utc"] = now_utc()
    persistence = persist_data(data)
    data["_persistence"] = persistence
    return data, pages.completion_page(COMPLETION_URL, persistence_ok=persistence.get("ok", False))


def experiment(parameters):
    return build_experiment(parameters)


if __name__ == "__main__":
    kesar(experiment)

