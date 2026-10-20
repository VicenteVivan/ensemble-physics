"""HTML fragments for Experiment 1."""

import html
import json

from kesar import (
    a_,
    div_,
    h1_,
    h2_,
    img_,
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


def general_instructions_page():
    return panel(
        "Welcome to the experiment",
        p_(class_="lead")(
            "There are two sections of 60 trials. In each, compare a second physical event with the first and judge whether its object or group was lighter or heavier."
        ),
        p_()("Every 10 trials you will see your score. Please do not use the browser Back button."),
    )


def section_instructions_page(section, number):
    single = section == "single"
    subject = "ball" if single else "group of balls"
    tutorial = "static/tutorial/images/tutorial.gif" if single else "static/tutorial/images/tutorial-multi.gif"
    return panel(
        f"Section {number}: {'single objects' if single else 'groups of objects'}",
        p_()(
            f"Each trial shows two videos of a {subject} dropping onto a cloth. Decide whether the {subject} in the second video was lighter or heavier than in the first."
        ),
        p_()("Differences may be subtle. Use the left/right choices and pay close attention to the motion and cloth deformation."),
        img_(class_="tutorial", src=tutorial, alt="Example trial", draggable="false"),
    )


def understanding_page():
    return panel(
        "Understanding check",
        div_(class_="question-block")(
            h2_()("1. What is your primary task?"),
            radio("question1", "A", "Judge color"),
            radio("question1", "B", "Judge size", required=False),
            radio("question1", "C", "Judge weight", required=False),
            radio("question1", "D", "Judge speed", required=False),
        ),
        div_(class_="question-block")(
            h2_()("2. What do the videos show?"),
            radio("question2", "A", "Balls colliding"),
            radio("question2", "B", "Balls floating", required=False),
            radio("question2", "C", "Balls rolling downhill", required=False),
            radio("question2", "D", "Balls being dropped onto a cloth", required=False),
        ),
    )


def retry_page():
    return panel(
        "Please review the instructions",
        p_()("At least one answer was incorrect. Review the section instructions and then try the check again."),
    )


def practice_intro_page():
    return panel(
        "Practice trials",
        p_()("You will complete two practice comparisons. Both must be correct before the main trials begin."),
    )


def practice_feedback_page():
    return panel(
        "Practice feedback",
        p_()("At least one practice answer was incorrect. Please watch both comparisons carefully and try again."),
    )


def ready_page():
    return panel(
        "Ready to begin",
        p_()("You completed the practice. The next page starts the 60 recorded trials for this section."),
    )


def trial_page(title, video1, video2, *, section, practice=False):
    return section_(class_="panel trial-panel")(
        h1_(class_="progress")(safe(title)),
        input_(id_="video1_path", type_="hidden", value=video1),
        input_(id_="video2_path", type_="hidden", value=video2),
        input_(id_="perception", type_="hidden", name="perception", value=""),
        input_(id_="reaction_time", type_="hidden", name="time", value=""),
        input_(id_="trial_section", type_="hidden", name="trial_section", value=section),
        input_(id_="practice", type_="hidden", value="1" if practice else "0"),
        div_(id_="trial-stage", class_="trial-stage")(
            video_(id_="trial-video", muted=True, playsinline=True, preload="auto")(""),
            div_(id_="fixation", class_="fixation", hidden=True)("+"),
            div_(id_="choice-screen", class_="choice-screen", hidden=True)(
                p_(id_="choice-question", class_="trial-question")(""),
                div_(class_="trial-choices")(
                    input_(id_="lighter", type_="button", value="← Lighter"),
                    input_(id_="heavier", type_="button", value="Heavier →"),
                ),
            ),
            p_(id_="trial-error", class_="error", hidden=True)(""),
        ),
        script_(src="static/pair_trial.js")(""),
    )


def score_page(correct, possible, total):
    return panel(
        "Score update",
        p_(class_="score")(f"You earned {int(correct)} of {int(possible)} points in the last 10 trials."),
        p_()(f"Running total: {int(total)} points."),
    )


def completion_page(redirect_url="", persistence_ok=True):
    message = "Your responses have been recorded." if persistence_ok else "The experiment finished, but saving reported an error. Please contact the researcher before closing this page."
    link = a_(class_="button-link", href=redirect_url)("Return to Prolific") if redirect_url else ""
    redirect_script = ""
    if redirect_url and persistence_ok:
        redirect_script = script_()(
            "setTimeout(function(){ window.location.assign(" + json.dumps(redirect_url) + "); }, 3000);"
        )
    return panel("Thank you", p_()(message), link, redirect_script)
