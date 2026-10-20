"""Run Experiment 2: mass discrimination and change localization."""

from __future__ import annotations

import os
import random
import hashlib
import json
import math
from datetime import datetime, timezone

import pages
from kesar import kesar
from protocol import (
    APP_ROOT,
    REWARD_INTERVAL,
    SECTION1_CATCH_INTERVAL,
    SECTION1_CATCH_TRIALS,
    SECTION1_NORMAL_TRIALS,
    SECTION1_TOTAL_TRIALS,
    SECTION2_TOTAL_TRIALS,
    SOURCE_COMMIT,
    catch_pair,
    check_understanding_section1,
    check_understanding_section2,
    choose_video_pair,
    grid_choice_correct,
    group_choice_correct,
    group_response_label,
    individual_choice_correct,
    individual_response_label,
    one,
    parameter_url,
    parse_grid_choice,
    place_catch_trials,
)
from send_data import persist_data


EXPERIMENT_NAME = "things-vs-stuff-experiment-2-combined"
EXPERIMENT_VERSION = "paper-protocol-ajax-2-submission-safety"
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


def trial_provenance(fields, pair, parameter_path, *, highlighted=None):
    """Retain client presentation evidence, bound to the server's accepted page."""
    events = json.loads(one(fields, "presentation_log"))
    if not isinstance(events, list) or not 1 <= len(events) <= 32:
        raise ValueError("Missing presentation evidence")
    if any(not isinstance(event, dict) or not isinstance(event.get('event'), str) for event in events):
        raise ValueError("Invalid presentation event")
    times = [event.get('t_ms') for event in events]
    if any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in times):
        raise ValueError("Invalid presentation timing")
    if times != sorted(times):
        raise ValueError("Presentation events out of order")
    videos = [(e['event'], e.get('path')) for e in events if e['event'].startswith('video-')]
    expected = [(kind, pair[video]) for video in ['video1', 'video2']
                for kind in ['video-started', 'video-ended']]
    if videos != expected:
        raise ValueError("Both assigned videos must finish before answering")
    sequence = ['parameters-loaded'] + (['highlighted-cell'] if highlighted is not None else [])
    sequence += ['video-started', 'video-ended', 'video-started', 'video-ended', 'choice']
    sequence += ([] if highlighted is not None else ['grid-choice']) + ['response-submitted']
    if [e['event'] for e in events if e['event'] != 'trial-ready'] != sequence:
        raise ValueError("Incomplete or out-of-order trial presentation")
    if [e.get('path') for e in events if e['event'] == 'parameters-loaded'] != [parameter_path]:
        raise ValueError("Missing parameter-load evidence")
    if [e.get('value') for e in events if e['event'] == 'choice'] != [int(one(fields, 'perception'))]:
        raise ValueError("Answer differs from first recorded choice")
    kind = 'highlighted-cell' if highlighted is not None else 'grid-choice'
    coordinate = highlighted if highlighted is not None else parse_grid_choice(one(fields, 'grid_choice'))
    if [e.get('coordinate') for e in events if e['event'] == kind] != [coordinate]:
        raise ValueError("Displayed/selected coordinate does not match")
    token = one(fields, '__page_token__')
    if not token:
        raise ValueError("No accepted page identity")
    return {
        'page_token': token,
        'page_issued_at_utc': one(fields, '__page_issued_at_utc__'),
        'response_received_at_utc': one(fields, '__response_received_at_utc__'),
        'parameter_path': parameter_path,
        'parameter_sha256': hashlib.sha256((APP_ROOT / parameter_path).read_bytes()).hexdigest(),
        'client_presentation_events': events,
        'client_scoring': {key: one(fields, key) for key in
                           ('perception_correct', 'grid_choice_correct', 'highlighted_cell_changed')},
    }


def tutorial_and_check(section):
    checker = check_understanding_section1 if section == 1 else check_understanding_section2
    yield pages.tutorial_page(section)
    while True:
        fields = yield pages.understanding_page(section)
        if checker(fields):
            return
        yield pages.retry_page()
        yield pages.tutorial_page(section)


def practice_section1():
    while True:
        yield pages.practice_intro_page(1)
        first_pair = catch_pair("light2heavy")
        first = yield pages.group_trial_page(
            "Practice (1/2)", first_pair, parameter_url(first_pair), practice=True
        )
        second_pair = catch_pair("heavy2light")
        second = yield pages.group_trial_page(
            "Practice (2/2)", second_pair, parameter_url(second_pair), practice=True
        )
        checks = (
            one(first, "perception_correct") == "1",
            one(first, "grid_choice_correct") == "1",
            one(second, "perception_correct") == "1",
            one(second, "grid_choice_correct") == "1",
        )
        if all(checks):
            return
        yield pages.practice_feedback_page()


def practice_section2():
    while True:
        yield pages.practice_intro_page(2)
        specifications = (
            ("light2heavy", "true"),
            ("heavy2light", "false"),
            ("heavy2light", "true"),
        )
        correct = []
        for index, (kind, ask_changed) in enumerate(specifications, start=1):
            pair = catch_pair(kind)
            fields = yield pages.individual_trial_page(
                f"Practice ({index}/3)",
                pair,
                parameter_url(pair),
                ask_changed=ask_changed,
                practice=True,
            )
            correct.append(one(fields, "perception_correct") == "1")
        if all(correct):
            return
        yield pages.practice_feedback_page()


def run_section1(rng):
    catch_positions = set(
        place_catch_trials(
            SECTION1_NORMAL_TRIALS,
            SECTION1_CATCH_TRIALS,
            SECTION1_CATCH_INTERVAL,
        )
    )
    trials = {}
    total_points = 0
    interval_points = 0

    for index in range(SECTION1_TOTAL_TRIALS):
        pair = (
            catch_pair(rng.choice(["light2heavy", "heavy2light"]))
            if index in catch_positions
            else choose_video_pair(rng)
        )
        parameter_path = parameter_url(pair)
        fields = yield pages.group_trial_page(
            f"({index + 1}/{SECTION1_TOTAL_TRIALS})", pair, parameter_path
        )
        choice = int(one(fields, "perception"))
        prediction = group_response_label(choice)
        raw_grid_choice = one(fields, "grid_choice")
        provenance = trial_provenance(fields, pair, parameter_path)
        perception_correct = group_choice_correct(pair, choice)
        localization_correct = grid_choice_correct(parameter_path, raw_grid_choice)
        points = int(perception_correct) + int(localization_correct)
        total_points += points
        interval_points += points

        trials[f"trial_{index}"] = {
            "video1": pair["video1"],
            "video2": pair["video2"],
            "comparison_type": pair["comparison_type"],
            "is_catch": index in catch_positions,
            "prediction": prediction,
            "grid_choice": raw_grid_choice,
            "reaction_time": int(one(fields, "time", "0") or 0),
            "time_grid_choice": int(one(fields, "time_grid_choice", "0") or 0),
            "perception_correct": "1" if perception_correct else "0",
            "grid_choice_correct": "1" if localization_correct else "0",
            "order": index,
            "timestamp": now_utc(),
            "provenance": provenance,
        }

        if (index + 1) % REWARD_INTERVAL == 0:
            yield pages.score_page(1, interval_points, REWARD_INTERVAL * 2, total_points)
            interval_points = 0

    return {"trials": trials, "total_points": total_points}


def run_section2(rng):
    trials = {}
    total_points = 0
    interval_points = 0

    for index in range(SECTION2_TOTAL_TRIALS):
        pair = choose_video_pair(rng)
        parameter_path = parameter_url(pair)
        fields = yield pages.individual_trial_page(
            f"({index + 1}/{SECTION2_TOTAL_TRIALS})", pair, parameter_path
        )
        choice = int(one(fields, "perception"))
        prediction = individual_response_label(choice)
        raw_highlighted = one(fields, "highlighted_cell")
        highlighted = parse_grid_choice(raw_highlighted)
        highlighted_changed = grid_choice_correct(parameter_path, raw_highlighted)
        provenance = trial_provenance(fields, pair, parameter_path, highlighted=highlighted)
        correct = individual_choice_correct(pair, choice, highlighted_changed)
        total_points += int(correct)
        interval_points += int(correct)

        trials[f"trial_{index}"] = {
            "video1": pair["video1"],
            "video2": pair["video2"],
            "comparison_type": pair["comparison_type"],
            "is_catch": False,
            "prediction": prediction,
            "reaction_time": int(one(fields, "time_perception", "0") or 0),
            "perception_correct": "1" if correct else "0",
            "highlighted_cell_changed": "1" if highlighted_changed else "0",
            "highlighted_cell": highlighted,
            "order": index,
            "timestamp": now_utc(),
            "provenance": provenance,
        }

        if (index + 1) % REWARD_INTERVAL == 0:
            yield pages.score_page(2, interval_points, REWARD_INTERVAL, total_points)
            interval_points = 0

    return {"trials": trials, "total_points": total_points}


def build_experiment(parameters, *, rng=None):
    rng = random if rng is None else rng
    started = now_utc()
    prolific = prolific_metadata(parameters)
    data = {
        "experiment1": {"trials": {}},
        "experiment2": {"trials": {}},
        "timestamp": started,
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
            "submission_events": parameters.get("__submission_events__", []),
        },
        "_quality": {"quiz_attempts": {"section1": 0, "section2": 0}, "excluded": False, "notes": []},
    }

    consent = yield pages.consent_page()
    if not eligible(consent):
        data["_quality"]["excluded"] = True
        data["_quality"]["notes"].append("participant_not_eligible_or_did_not_consent")
        data["_metadata"]["completed_at_utc"] = now_utc()
        persistence = persist_data(data)
        data["_persistence"] = persistence
        return data, pages.completion_page("", persistence_ok=persistence.get("ok", False))

    yield pages.general_page()
    yield from tutorial_and_check(1)
    yield from practice_section1()
    yield pages.ready_page(1)
    section1 = yield from run_section1(rng)
    data["experiment1"] = section1

    yield pages.transition_page()
    yield from tutorial_and_check(2)
    yield from practice_section2()
    yield pages.ready_page(2)
    section2 = yield from run_section2(rng)
    data["experiment2"] = section2

    data["combined_total_points"] = section1["total_points"] + section2["total_points"]
    data["_metadata"]["completed_at_utc"] = now_utc()
    persistence = persist_data(data)
    data["_persistence"] = persistence
    return data, pages.completion_page(COMPLETION_URL, persistence_ok=persistence.get("ok", False))


def experiment(parameters):
    return build_experiment(parameters)


if __name__ == "__main__":
    kesar(experiment)
