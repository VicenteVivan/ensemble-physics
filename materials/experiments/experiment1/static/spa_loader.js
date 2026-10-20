(function () {
  if (window.KESAR_SPA_LOADER_INSTALLED) return;
  window.KESAR_SPA_LOADER_INSTALLED = true;

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

  function showRecovery(error) {
    console.error("The response was accepted but the next page could not be displayed", error);
    document.body.innerHTML =
      '<main class="page-shell"><section class="panel"><h1>Reload needed</h1>' +
      "<p>Your last response was received, but the next page could not be displayed.</p>" +
      '<p>Reload once. If this message returns, contact the researcher.</p>' +
      '<button type="button" id="reload">Reload</button></section></main>';
    document.getElementById("reload").addEventListener("click", () => window.location.reload());
  }

  document.addEventListener(
    "submit",
    async function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      event.preventDefault();
      if (window.KESAR_SUBMITTING) return;
      window.KESAR_SUBMITTING = true;

      let response;
      try {
        response = await fetch(form.action || window.location.href, {
          method: "POST",
          body: new URLSearchParams(new FormData(form)),
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Kesar-Ajax": "1",
          },
        });
      } catch (error) {
        window.KESAR_SUBMITTING = false;
        form.submit();
        return;
      }

      if (!response.ok) {
        window.KESAR_SUBMITTING = false;
        form.submit();
        return;
      }

      try {
        await replacePage(await response.text());
      } catch (error) {
        showRecovery(error);
      }
    },
    true
  );
})();
