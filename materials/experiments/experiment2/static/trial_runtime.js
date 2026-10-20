(function () {
  if (window.ThingsStuffTrialRuntime) return;

  function cleanCoordinate(x, z) {
    const xValues = [-2, -1, 0, 1, 2];
    const zValues = [2, 1, 0, -1, -2];
    const gridSize = 2 * (5 / 3);
    const centerX = -2 / 3;
    const centerZ = 2 / 3;
    const adjustedX = x - centerX;
    const adjustedZ = z - centerZ;
    const nearest = (values, adjusted) => values.reduce((previous, current) => {
      const currentPosition = current * (gridSize / 5);
      const previousPosition = previous * (gridSize / 5);
      return Math.abs(currentPosition - adjusted) < Math.abs(previousPosition - adjusted)
        ? current
        : previous;
    });
    return { x: nearest(xValues, adjustedX), z: nearest(zValues, adjustedZ) };
  }

  function key(coordinate) {
    return coordinate.x + "," + coordinate.z;
  }

  // Exact homography induced by the four cloth-grid corners in the deployed
  // canvas (896 x 504): (374.5,182.7), (737.8,251.3),
  // (569.8,493.5), and (83.3,327.6).
  function projectToCloth(s, t) {
    const h = [
      227.09668606019841, -317.60499344207159, 374.5,
      22.208169160921472, 41.055151841264504, 182.7,
      -0.18460736505801245, -0.31698671599125605, 1,
    ];
    const denominator = h[6] * s + h[7] * t + h[8];
    return {
      x: (h[0] * s + h[1] * t + h[2]) / denominator,
      y: (h[3] * s + h[4] * t + h[5]) / denominator,
    };
  }

  function clothCells() {
    const cells = [];
    for (let row = 0; row < 5; row += 1) {
      for (let column = 0; column < 5; column += 1) {
        const s1 = column / 5;
        const s2 = (column + 1) / 5;
        const t1 = row / 5;
        const t2 = (row + 1) / 5;
        cells.push({
          coordinate: { x: -2 + row, z: 2 - column },
          corners: [
            projectToCloth(s1, t1),
            projectToCloth(s2, t1),
            projectToCloth(s2, t2),
            projectToCloth(s1, t2),
          ],
        });
      }
    }
    return cells;
  }

  class Runtime {
    constructor() {
      this.form = document.querySelector("form");
      this.submitButton = document.getElementById("submit");
      this.stage = document.getElementById("trial-stage");
      this.video = document.getElementById("trial-video");
      this.fixation = document.getElementById("fixation");
      this.gridScreen = document.getElementById("grid-screen");
      this.gridQuestion = document.getElementById("grid-question");
      this.grid = document.getElementById("grid");
      this.choiceScreen = document.getElementById("choice-screen");
      this.choiceQuestion = document.getElementById("choice-question");
      this.choices = document.getElementById("trial-choices");
      this.errorBox = document.getElementById("trial-error");
      this.video1 = document.getElementById("video1_path").value;
      this.video2 = document.getElementById("video2_path").value;
      this.parameterPath = document.getElementById("parameter_path").value;
      this.destroyed = false;
      this.submitted = false;
      this.failed = false;
      this.startedAt = performance.now();
      this.events = [];
      this.record("trial-ready", { client_time_utc: new Date().toISOString() });
      this.timers = new Set();
      this.cleanupCallbacks = [];
      this.submitButton.style.display = "none";
      this.submitButton.disabled = true;
      this.video.hidden = true;
      this.stage.classList.add("blank");
    }

    record(event, details = {}) {
      this.events.push({ event, t_ms: Math.max(0, performance.now() - this.startedAt), ...details });
    }

    sleep(milliseconds) {
      return new Promise((resolve) => {
        const id = window.setTimeout(() => {
          this.timers.delete(id);
          resolve();
        }, milliseconds);
        this.timers.add(id);
      });
    }

    async blank(milliseconds) {
      if (this.destroyed) return;
      this.video.hidden = true;
      this.gridScreen.hidden = true;
      this.choiceScreen.hidden = true;
      this.fixation.hidden = true;
      this.stage.classList.add("blank");
      await this.sleep(milliseconds);
    }

    async showFixation(milliseconds) {
      if (this.destroyed) return;
      this.fixation.hidden = false;
      await this.sleep(milliseconds);
      this.fixation.hidden = true;
    }

    play(path) {
      return new Promise((resolve, reject) => {
        if (this.destroyed) return resolve();
        this.stage.classList.remove("blank");
        this.video.hidden = false;
        this.video.src = path;
        this.video.currentTime = 0;
        const remove = () => {
          this.video.removeEventListener("ended", done);
          this.video.removeEventListener("error", failed);
          this.video.removeEventListener("playing", started);
        };
        const started = () => this.record("video-started", { path });
        const done = () => { this.record("video-ended", { path, duration_seconds: this.video.duration }); remove(); resolve(); };
        const failed = () => { remove(); reject(new Error("Could not play " + path)); };
        this.video.addEventListener("ended", done, { once: true });
        this.video.addEventListener("error", failed, { once: true });
        this.video.addEventListener("playing", started, { once: true });
        this.cleanupCallbacks.push(remove);
        const promise = this.video.play();
        if (promise && typeof promise.catch === "function") promise.catch(failed);
      });
    }

    async playPair() {
      await this.blank(750);
      await this.showFixation(750);
      await this.play(this.video1);
      await this.blank(750);
      await this.play(this.video2);
      await this.blank(750);
    }

    async changedCoordinates() {
      const response = await fetch(this.parameterPath, { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load " + this.parameterPath);
      const items = await response.json();
      if (!Array.isArray(items) || items.length !== 25 ||
          items.some((item) => !item || !Number.isFinite(item.x) || !Number.isFinite(item.z))) {
        throw new Error("Invalid stimulus parameters");
      }
      if (new Set(items.map((item) => key(cleanCoordinate(item.x, item.z)))).size !== 25) {
        throw new Error("Stimulus grid locations are not unique");
      }
      const unique = new Map();
      items.filter((item) => Object.prototype.hasOwnProperty.call(item, "mass_original"))
        .map((item) => cleanCoordinate(item.x, item.z))
        .forEach((coordinate) => unique.set(key(coordinate), coordinate));
      const expected = this.parameterPath.includes("/catch/") ? 15 : 5;
      if (unique.size !== expected) throw new Error("Incomplete changed-location answer key");
      this.record("parameters-loaded", { path: this.parameterPath, changed_locations: unique.size });
      return Array.from(unique.values());
    }

    showChoices(question, options, onChoice) {
      this.stage.classList.remove("blank");
      this.video.hidden = true;
      this.gridScreen.hidden = true;
      this.choiceScreen.hidden = false;
      this.choiceQuestion.textContent = question;
      this.choices.innerHTML = "";
      const started = performance.now();
      let chosen = false;
      const choose = (value) => {
        if (chosen || this.submitted || this.destroyed || this.failed || this.choiceScreen.hidden) return;
        chosen = true;
        buttons.forEach((button) => { button.disabled = true; });
        window.removeEventListener("keydown", keydown);
        this.record("choice", { value });
        onChoice(value, Math.max(0, Math.round(performance.now() - started)));
      };
      const buttons = options.map((option) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "trial-choice";
        button.textContent = option.label;
        const click = () => choose(option.value);
        button.addEventListener("click", click);
        this.cleanupCallbacks.push(() => button.removeEventListener("click", click));
        this.choices.appendChild(button);
        return button;
      });
      const keydown = (event) => {
        const match = options.find((option) => option.keys.includes(event.code));
        if (!match) return;
        event.preventDefault();
        choose(match.value);
      };
      window.addEventListener("keydown", keydown);
      this.cleanupCallbacks.push(() => window.removeEventListener("keydown", keydown));
      return buttons;
    }

    showGrid(question, onChoose, highlighted) {
      this.stage.classList.remove("blank");
      this.video.hidden = true;
      this.choiceScreen.hidden = true;
      this.gridScreen.hidden = false;
      this.gridQuestion.textContent = question;
      this.grid.innerHTML = "";
      const highlightedKey = highlighted ? key(highlighted) : "";
      if (highlighted) this.record("highlighted-cell", { coordinate: highlighted });
      const namespace = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(namespace, "svg");
      svg.setAttribute("viewBox", "0 0 896 504");
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", "5 by 5 landing grid");
      let chosen = false;
      const choose = (coordinate) => {
        if (chosen || this.submitted || this.destroyed || this.failed || this.gridScreen.hidden) return;
        chosen = true;
        svg.querySelectorAll("polygon").forEach((cell) => {
          cell.setAttribute("aria-disabled", "true");
          cell.setAttribute("tabindex", "-1");
        });
        this.record("grid-choice", { coordinate });
        onChoose(coordinate);
      };
      clothCells().forEach((cell) => {
        const polygon = document.createElementNS(namespace, "polygon");
        polygon.setAttribute("points", cell.corners.map((point) => point.x + "," + point.y).join(" "));
        polygon.setAttribute("class", "grid-cell" + (key(cell.coordinate) === highlightedKey ? " highlighted" : ""));
        polygon.setAttribute("aria-label", "grid cell " + cell.coordinate.x + ", " + cell.coordinate.z);
        if (onChoose) {
          polygon.setAttribute("tabindex", "0");
          polygon.setAttribute("role", "button");
          const click = () => choose(cell.coordinate);
          const keydown = (event) => {
            if (event.code === "Enter" || event.code === "Space") {
              event.preventDefault();
              choose(cell.coordinate);
            }
          };
          polygon.addEventListener("click", click, { once: true });
          polygon.addEventListener("keydown", keydown);
          this.cleanupCallbacks.push(() => {
            polygon.removeEventListener("click", click);
            polygon.removeEventListener("keydown", keydown);
          });
        }
        svg.appendChild(polygon);
      });
      this.grid.appendChild(svg);
    }

    submit() {
      if (this.submitted || this.destroyed || this.failed) return;
      this.submitted = true;
      this.record("response-submitted");
      document.getElementById("presentation_log").value = JSON.stringify(this.events);
      this.submitButton.disabled = false;
      if (typeof this.form.requestSubmit === "function") this.form.requestSubmit(this.submitButton);
      else this.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }

    fail(error) {
      if (this.destroyed) return;
      this.failed = true;
      this.errorBox.hidden = false;
      this.errorBox.textContent = "This trial could not be loaded correctly. Please stop and contact the researcher. Do not reload or restart the study.";
      console.error(error);
    }

    cleanup() {
      this.destroyed = true;
      this.timers.forEach((id) => clearTimeout(id));
      this.timers.clear();
      this.cleanupCallbacks.splice(0).forEach((callback) => {
        try { callback(); } catch (error) {}
      });
      try {
        this.video.pause();
        this.video.removeAttribute("src");
        this.video.load();
      } catch (error) {}
    }
  }

  function massCode(path) {
    if (path.includes("/catch/")) {
      if (path.includes("m320")) return -1;
      if (path.includes("m20")) return 1;
    }
    if (path.includes("/heavier/")) return 1;
    if (path.includes("/lighter/")) return -1;
    return 0;
  }

  window.ThingsStuffTrialRuntime = { Runtime, key, massCode };
})();
