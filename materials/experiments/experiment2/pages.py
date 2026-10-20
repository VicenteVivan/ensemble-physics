"""HTML fragments for the two-section Experiment 2 application."""

import html
import json

from kesar import (
    a_,
    div_,
    h1_,
    h2_,
    input_,
    label_,
    p_,
    script_,
    section_,
    span_,
    strong_,
    video_,
)


def safe(value):
    return html.escape(str(value), quote=True)


def panel(title, *children, lead=None, class_name="panel"):
    return section_(class_=class_name)(
        h1_()(safe(title)),
        p_(class_="lead")(safe(lead)) if lead else "",
        *children,
    )


def radio(name, value, label, *, required=True):
    return label_(class_="choice")(
        input_(type_="radio", name=name, value=value, required=required),
        span_()(safe(label)),
    )


def consent_page():
    return panel(
        "Online Consent Form",
        p_()(
            "This study asks you to judge the relative weight of objects in short physical simulations. "
            "Participation is voluntary, and you may stop at any time."
        ),
        div_(class_="question-block")(
            p_()(strong_()("I am age 18 or older.")),
            radio("eighteen", "yes", "Yes"),
            radio("eighteen", "no", "No", required=False),
        ),
        div_(class_="question-block")(
            p_()(strong_()("I have read and understand the information above.")),
            radio("understood", "yes", "Yes"),
            radio("understood", "no", "No", required=False),
        ),
        div_(class_="question-block")(
            p_()(strong_()("I want to participate and continue.")),
            radio("consent", "yes", "Yes"),
            radio("consent", "no", "No", required=False),
        ),
    )


def general_page():
    return panel(
        "Welcome",
        p_(class_="lead")(
            "This experiment has two consecutive sections of 60 trials. Both use matched videos of 25 marbles falling onto a cloth."
        ),
        p_()("Please do not use the browser Back button while the study is running."),
    )


def tutorial_page(section):
    if section == 1:
        title = "Section 1: group weight and changed location"
        copy = (
            "Judge whether the group in the second video is lighter or heavier than in the first. "
            "Then select one grid square where a changed marble landed."
        )
        video = "static/tutorial/videos/tutorial.mp4"
    else:
        title = "Section 2: one highlighted marble"
        copy = (
            "A grid square is highlighted before each pair. Judge only the marble landing there: "
            "lighter, the same, or heavier in the second video."
        )
        video = "static/tutorial/videos/tutorial_exp2.mp4"
    return panel(
        title,
        p_()(copy),
        video_(class_="tutorial-video", src=video, controls=True, muted=True, playsinline=True, loop=True)(""),
    )


def understanding_page(section):
    if section == 1:
        return panel(
            "Understanding check",
            div_(class_="question-block")(
                h2_()("1. What is the primary judgment?"),
                radio("question1", "A", "Color"),
                radio("question1", "B", "Size", required=False),
                radio("question1", "C", "Weight", required=False),
                radio("question1", "D", "Speed", required=False),
            ),
            div_(class_="question-block")(
                h2_()("2. What do the videos show?"),
                radio("question2", "A", "Marbles colliding"),
                radio("question2", "B", "Marbles floating", required=False),
                radio("question2", "C", "Marbles rolling downhill", required=False),
                radio("question2", "D", "Marbles being dropped onto a cloth", required=False),
            ),
        )
    return panel(
        "Understanding check",
        div_(class_="question-block")(
            h2_()("1. What is the primary judgment?"),
            radio("question1", "A", "Color of all marbles"),
            radio("question1", "B", "Size of the highlighted marble", required=False),
            radio("question1", "C", "Weight of one marble", required=False),
            radio("question1", "D", "Weight of all marbles", required=False),
        ),
        div_(class_="question-block")(
            h2_()("2. What do the videos show?"),
            radio("question2", "A", "Marbles colliding"),
            radio("question2", "B", "Marbles floating", required=False),
            radio("question2", "C", "Marbles rolling downhill", required=False),
            radio("question2", "D", "Marbles being dropped onto a cloth", required=False),
        ),
        div_(class_="question-block")(
            h2_()("3. Which marble should you judge?"),
            radio("question3", "A", "All marbles"),
            radio("question3", "B", "The fastest marble", required=False),
            radio("question3", "C", "The marble landing in the highlighted square", required=False),
            radio("question3", "D", "The highest-bouncing marble", required=False),
        ),
    )


def retry_page():
    return panel("Please review the instructions", p_()("At least one answer was incorrect. Review the tutorial and try again."))


def practice_intro_page(section):
    count = 2 if section == 1 else 3
    return panel("Practice trials", p_()(f"You will complete {count} practice trials. All judgments must be correct before continuing."))


def practice_feedback_page():
    return panel("Practice feedback", p_()("At least one practice response was incorrect. Please review the task and try again."))


def ready_page(section):
    return panel("Ready to begin", p_()(f"The next page starts the 60 recorded trials in Section {section}."))


def transition_page():
    return panel(
        "Section 1 complete",
        p_()("Take a short break if needed. The next pages explain the highlighted-marble task in Section 2."),
    )


def _trial_shell(title, pair, parameter_path, script_name, extra_fields=()):
    return section_(class_="panel trial-panel")(
        h1_(class_="progress")(safe(title)),
        input_(id_="video1_path", type_="hidden", value=pair["video1"]),
        input_(id_="video2_path", type_="hidden", value=pair["video2"]),
        input_(id_="parameter_path", type_="hidden", value=parameter_path),
        input_(id_="presentation_log", type_="hidden", name="presentation_log", value=""),
        *extra_fields,
        div_(id_="trial-stage", class_="trial-stage")(
            video_(id_="trial-video", muted=True, playsinline=True, preload="auto")(""),
            div_(id_="fixation", class_="fixation", hidden=True)("+"),
            div_(id_="grid-screen", class_="grid-screen", hidden=True)(
                p_(id_="grid-question", class_="trial-question")(""),
                div_(id_="grid", class_="grid", role="group", **{"aria-label": "5 by 5 landing grid"})(""),
            ),
            div_(id_="choice-screen", class_="choice-screen", hidden=True)(
                p_(id_="choice-question", class_="trial-question")(""),
                div_(id_="trial-choices", class_="trial-choices")(""),
            ),
            p_(id_="trial-error", class_="error", hidden=True)(""),
        ),
        script_(src="static/trial_runtime.js")(""),
        script_(src=script_name)(""),
    )


def group_trial_page(title, pair, parameter_path, *, practice=False):
    return _trial_shell(
        title,
        pair,
        parameter_path,
        "static/group_trial.js",
        (
            input_(id_="perception", type_="hidden", name="perception", value=""),
            input_(id_="grid_choice", type_="hidden", name="grid_choice", value=""),
            input_(id_="time_perception", type_="hidden", name="time", value=""),
            input_(id_="time_grid_choice", type_="hidden", name="time_grid_choice", value=""),
            input_(id_="perception_correct", type_="hidden", name="perception_correct", value=""),
            input_(id_="grid_choice_correct", type_="hidden", name="grid_choice_correct", value=""),
            input_(id_="practice", type_="hidden", value="1" if practice else "0"),
        ),
    )


def individual_trial_page(title, pair, parameter_path, *, ask_changed="random", practice=False):
    return _trial_shell(
        title,
        pair,
        parameter_path,
        "static/individual_trial.js",
        (
            input_(id_="ask_about_changed_cell", type_="hidden", value=ask_changed),
            input_(id_="perception", type_="hidden", name="perception", value=""),
            input_(id_="time_perception", type_="hidden", name="time_perception", value=""),
            input_(id_="perception_correct", type_="hidden", name="perception_correct", value=""),
            input_(id_="highlighted_cell_changed", type_="hidden", name="highlighted_cell_changed", value=""),
            input_(id_="highlighted_cell", type_="hidden", name="highlighted_cell", value=""),
            input_(id_="practice", type_="hidden", value="1" if practice else "0"),
        ),
    )


def score_page(section, correct, possible, total):
    return panel(
        "Score update",
        p_(class_="score")(f"You earned {int(correct)} of {int(possible)} points in the last 10 trials."),
        p_()(f"Section {section} running total: {int(total)} points."),
    )


def completion_page(redirect_url="", persistence_ok=True):
    message = "Your responses have been recorded." if persistence_ok else "The study finished, but saving reported an error. Contact the researcher before closing this page."
    link = a_(class_="button-link", href=redirect_url)("Return to Prolific") if redirect_url else ""
    redirect_script = ""
    if redirect_url and persistence_ok:
        redirect_script = script_()(
            "setTimeout(function(){ window.location.assign(" + json.dumps(redirect_url) + "); }, 3000);"
        )
    return panel("Thank you", p_()(message), link, redirect_script)
