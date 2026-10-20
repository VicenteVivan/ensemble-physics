"""Ajax-first Kesar: a small generator-driven experiment server.

The server deliberately has no database logic.  An experiment persists its own
completed document before returning its final page.
"""

from __future__ import annotations

import html
import http.server
import inspect
import os
import threading
import uuid
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
        window.KESAR_SUBMITTING = false;
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


def page(uid, *contents, disable_submit=False, title_text="Things vs Stuff") -> str:
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


def kesar(script, *, port=PORT):
    """Run ``script`` on a thread-per-request local HTTP server."""

    sessions = {}
    sessions_lock = threading.Lock()

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
            uid = uuid.uuid4().hex
            generator = _start_script(script, parameters)
            try:
                first_content = next(generator)
            except Exception as exc:
                self._html_headers(500)
                self.wfile.write(page(None, h1_()("Experiment unavailable"), p_()(html.escape(str(exc)))).encode())
                return

            with sessions_lock:
                sessions[uid] = generator
            self._html_headers()
            self.wfile.write(page(uid, first_content).encode("utf-8"))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            uid = fields.get("uid", [""])[0]
            with sessions_lock:
                generator = sessions.get(uid)
            if generator is None:
                self._html_headers(409)
                self.wfile.write(page(None, h1_()("Session expired"), p_()("Please return the study and contact the researcher.")).encode())
                return

            try:
                next_content = generator.send(fields)
                response = page(uid, next_content)
            except StopIteration as completed:
                _, goodbye = _completion_value(completed.value)
                with sessions_lock:
                    sessions.pop(uid, None)
                response = page(None, goodbye)
            except Exception as exc:
                with sessions_lock:
                    sessions.pop(uid, None)
                self._html_headers(500)
                self.wfile.write(page(None, h1_()("Experiment error"), p_()(html.escape(str(exc)))).encode())
                return

            self._html_headers()
            self.wfile.write(response.encode("utf-8"))

    print(f"Kesar serving {APP_ROOT} at http://127.0.0.1:{port}")
    with http.server.ThreadingHTTPServer(("", port), ExperimentHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
