"""Ajax-first Kesar: a small generator-driven experiment server.

The server deliberately has no database logic.  An experiment persists its own
completed document before returning its final page.
"""

from __future__ import annotations

import html
import hashlib
import http.server
import inspect
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "5000"))


class tag:
    def __init__(self, element_name: str, **attributes):
        self.name = element_name
        self.attributes = attributes

    def __str__(self) -> str:
        return self()

    def __call__(self, *children) -> str:
        def render_attribute(key, value):
            key = key.strip("_")
            if value is True:
                return key
            return f'{key}="{html.escape(str(value), quote=True)}"'

        attributes = "".join(
            f" {render_attribute(key, value)}"
            for key, value in self.attributes.items()
            if value is not None and value is not False
        )
        if not children:
            return f"<{self.name}{attributes}/>"
        return f"<{self.name}{attributes}>{' '.join(str(child) for child in children)}</{self.name}>"


for _element in (
    "a article body br button canvas div em fieldset footer form h1 h2 h3 "
    "head hr html img input label legend li link main meta ol p script section "
    "small span strong textarea title ul video"
).split():
    globals()[f"{_element}_"] = partial(tag, _element)


def _navigation_guard() -> str:
    return script_()(
        """
        if (typeof window.KESAR_SUBMITTING === 'undefined') window.KESAR_SUBMITTING = false;
        if (!window.KESAR_NAV_GUARD_INSTALLED) {
          window.KESAR_NAV_GUARD_INSTALLED = true;
          window.addEventListener('beforeunload', function (event) {
            if (window.KESAR_EXPERIMENT_COMPLETE || window.KESAR_SUBMITTING) return;
            event.preventDefault();
            event.returnValue = 'Leaving now may invalidate this response.';
            return event.returnValue;
          });
          history.pushState(null, '', window.location.href);
          window.addEventListener('popstate', function () {
            if (!window.KESAR_EXPERIMENT_COMPLETE) history.pushState(null, '', window.location.href);
          });
        }
        """
    )


def page(uid, *contents, disable_submit=False, title_text="Things vs Stuff", page_token=None) -> str:
    head = head_()(
        meta_(charset="utf-8"),
        meta_(name="viewport", content="width=device-width, initial-scale=1"),
        title_()(title_text),
        link_(rel="stylesheet", type_="text/css", href="static/styles.css"),
    )
    if uid is None:
        body = body_()(
            main_(class_="page-shell final-page")(*contents),
            script_(src="static/spa_loader.js")(""),
            script_()("window.KESAR_EXPERIMENT_COMPLETE = true;"),
        )
    else:
        body = body_()(
            main_(class_="page-shell")(
                form_(action="", method="POST", autocomplete="off")(
                    *contents,
                    input_(type_="hidden", name="uid", value=uid),
                    input_(type_="hidden", name="page_token", value=page_token or uuid.uuid4().hex),
                    div_(class_="actions")(
                        input_(
                            id_="submit",
                            type_="submit",
                            value="Next",
                            disabled=True if disable_submit else None,
                        )
                    ),
                )
            ),
            script_(src="static/spa_loader.js")(""),
            _navigation_guard(),
        )
    return "<!DOCTYPE html>" + html_()(head, body)


def _start_script(script, parameters):
    return script(parameters) if len(inspect.signature(script).parameters) else script()


def _completion_value(value):
    if isinstance(value, tuple) and len(value) == 2:
        return value
    return value, p_()("You have completed the experiment and may close this window.")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    generator: object
    events: list
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    issued_at: str = field(default_factory=_utc_now)
    lock: object = field(default_factory=threading.Lock)
    last_token: str | None = None
    last_payload_hash: str | None = None
    response: str = ""
    status: int = 200
    completed_at: float | None = None


def create_server(script, *, host="", port=PORT):
    """Build the HTTP server; a page token may advance its generator only once."""

    sessions = {}
    sessions_lock = threading.Lock()

    def prune_completed():
        # Keep a bounded final-response receipt so a lost completion reply can
        # be retried without persisting a participant twice. Active runs stay live.
        completed = sorted((s.completed_at, uid) for uid, s in sessions.items()
                           if s.completed_at is not None)
        cutoff = time.monotonic() - 600
        for index, (finished, uid) in enumerate(completed):
            if finished < cutoff or index < len(completed) - 512:
                sessions.pop(uid, None)

    class ExperimentHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(APP_ROOT), **kwargs)

        def _html_headers(self, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/":
                return super().do_GET()

            parameters = parse_qs(parsed.query, keep_blank_values=True)
            parameters["__user_agent__"] = [self.headers.get("User-Agent", "")]
            events = []
            parameters["__submission_events__"] = events
            uid = uuid.uuid4().hex
            generator = _start_script(script, parameters)
            try:
                first_content = next(generator)
            except Exception as exc:
                self._html_headers(500)
                self.wfile.write(page(None, h1_()("Experiment unavailable"), p_()(html.escape(str(exc)))).encode())
                return

            with sessions_lock:
                prune_completed()
                session = Session(generator, events)
                sessions[uid] = session
            self._html_headers()
            self.wfile.write(page(uid, first_content, page_token=session.token).encode("utf-8"))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            uid = fields.get("uid", [""])[0]
            with sessions_lock:
                prune_completed()
                session = sessions.get(uid)
            if session is None:
                self._html_headers(409)
                self.wfile.write(page(None, h1_()("Session expired"), p_()("Please return the study and contact the researcher.")).encode())
                return

            # Validate identity and advance under the SAME per-session lock.
            # A lock around dictionary access alone does not protect send().
            with session.lock:
                token = fields.get("page_token", [""])[0]
                payload_hash = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
                received_at = _utc_now()
                if (token and token == session.last_token
                        and payload_hash == session.last_payload_hash):
                    session.events.append({"event": "duplicate_replayed", "page_token": token,
                                           "at_utc": received_at})
                    status, response = session.status, session.response
                elif (not token or token != session.token or session.completed_at is not None
                      or len(fields.get("uid", [])) != 1 or len(fields.get("page_token", [])) != 1):
                    session.events.append({"event": "stale_or_conflicting_rejected", "at_utc": received_at})
                    status = 409
                    response = page(None, h1_()("Response could not be matched"),
                                    p_()("Please stop and contact the researcher. Do not restart the study."))
                else:
                    session.events.append({"event": "accepted", "page_token": token,
                                           "at_utc": received_at})
                    # Never accept client-supplied values for server provenance.
                    submitted = {k: v for k, v in fields.items() if not k.startswith("__")}
                    submitted.update(__page_token__=[token],
                                     __page_issued_at_utc__=[session.issued_at],
                                     __response_received_at_utc__=[received_at])
                    try:
                        next_content = session.generator.send(submitted)
                        session.token = uuid.uuid4().hex
                        session.issued_at = _utc_now()
                        status, response = 200, page(uid, next_content, page_token=session.token)
                    except StopIteration as completed:
                        _, goodbye = _completion_value(completed.value)
                        session.completed_at = time.monotonic()
                        session.generator = None
                        status, response = 200, page(None, goodbye)
                    except Exception:
                        session.completed_at = time.monotonic()
                        session.generator = None
                        status, response = 500, page(None, h1_()("Experiment error"),
                            p_()("Please stop and contact the researcher. Do not restart the study."))
                    session.last_token, session.last_payload_hash = token, payload_hash
                    session.status, session.response = status, response

            self._html_headers(status)
            self.wfile.write(response.encode("utf-8"))

    class ExperimentServer(http.server.ThreadingHTTPServer):
        # Allow a brief burst of connections while the accept loop starts their
        # worker threads; the stdlib default backlog of five is easily exhausted.
        request_queue_size = 64

    return ExperimentServer((host, port), ExperimentHandler)


def kesar(script, *, port=PORT):
    """Run ``script`` on a thread-per-request HTTP server."""
    print(f"Kesar serving {APP_ROOT} at http://127.0.0.1:{port}")
    with create_server(script, port=port) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
