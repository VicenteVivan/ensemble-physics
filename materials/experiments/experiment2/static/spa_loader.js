(function () {
  if (window.KESAR_SPA_LOADER_INSTALLED) return;
  window.KESAR_SPA_LOADER_INSTALLED = true;
  let inFlight = false;

  function stopCurrentPage() {
    try {
      if (typeof window.KESAR_PAGE_CLEANUP === "function") {
        window.KESAR_PAGE_CLEANUP();
      }
    } catch (error) {
      console.warn("Page cleanup failed", error);
    }
    window.KESAR_PAGE_CLEANUP = null;
    document.querySelectorAll("audio,video").forEach((media) => {
      try {
        media.pause();
        media.currentTime = 0;
      } catch (error) {}
    });
  }

  async function runScript(oldScript) {
    const src = oldScript.getAttribute("src");
    if (src && new URL(src, window.location.href).pathname.endsWith("/static/spa_loader.js")) {
      return;
    }
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      Array.from(oldScript.attributes).forEach((attribute) => {
        script.setAttribute(attribute.name, attribute.value);
      });
      if (src) {
        script.onload = resolve;
        script.onerror = () => reject(new Error("Could not load " + src));
      } else {
        script.textContent = oldScript.textContent || "";
      }
      document.body.appendChild(script);
      if (!src) resolve();
    });
  }

  async function replacePage(markup) {
    const incoming = new DOMParser().parseFromString(markup, "text/html").body;
    if (!incoming) throw new Error("Ajax response had no body");

    stopCurrentPage();
    const scripts = Array.from(incoming.querySelectorAll("script"));
    scripts.forEach((script) => script.remove());

    Array.from(document.body.attributes).forEach((attribute) => {
      document.body.removeAttribute(attribute.name);
    });
    Array.from(incoming.attributes).forEach((attribute) => {
      document.body.setAttribute(attribute.name, attribute.value);
    });
    document.body.innerHTML = incoming.innerHTML;
    for (const script of scripts) await runScript(script);
    window.KESAR_SUBMITTING = false;
    window.scrollTo(0, 0);
  }

  function showRecovery(message, retry) {
    stopCurrentPage();
    window.KESAR_SUBMITTING = false;
    document.body.innerHTML =
      '<main class="page-shell"><section class="panel"><h1>Study paused</h1>' +
      '<p id="recovery-message"></p><p>If this continues, contact the researcher. Please do not reload or restart.</p>' +
      (retry ? '<button type="button" id="retry-response">Try again</button>' : '') +
      '</section></main>';
    document.getElementById("recovery-message").textContent = message;
    if (retry) {
      const button = document.getElementById("retry-response");
      button.addEventListener("click", () => {
        if (button.disabled) return;
        button.disabled = true;
        window.KESAR_SUBMITTING = true;
        retry();
      });
    }
  }

  async function displayAccepted(markup) {
    try {
      await replacePage(markup);
      inFlight = false;
    } catch (error) {
      console.error("Accepted response; next page display failed", error);
      // Retry display of the already received page, never submit again here.
      showRecovery("Your answer was received, but the next page could not be displayed.",
        () => displayAccepted(markup));
    }
  }

  async function sendFrozen(url, body) {
    let response, markup;
    try {
      response = await fetch(url, {
        method: "POST", body,
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Kesar-Ajax": "1",
        },
      });
      if (response.ok) markup = await response.text();
    } catch (error) {
      // The server may already have accepted it. Reuse exactly the same token
      // and payload on explicit retry; never rebuild fields or use form.submit().
      showRecovery("We could not confirm that your answer was received. Try sending the same answer again.",
        () => sendFrozen(url, body));
      return;
    }
    if (!response.ok) {
      showRecovery("Your answer could not be confirmed. Please stop and contact the researcher.");
      return;
    }
    await displayAccepted(markup);
  }

  document.addEventListener(
    "submit",
    async function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      event.preventDefault();
      if (inFlight || !form.isConnected) return;
      // Capture before disabling controls; later clicks cannot alter retries.
      const body = new URLSearchParams(new FormData(form)).toString();
      const url = form.action || window.location.href;
      inFlight = true;
      window.KESAR_SUBMITTING = true;
      form.querySelectorAll('button, input[type="submit"]').forEach((button) => { button.disabled = true; });
      await sendFrozen(url, body);
    },
    true
  );
})();
