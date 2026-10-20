(function () {
  const library = window.ThingsStuffTrialRuntime;
  if (!library) throw new Error("trial_runtime.js must load before individual_trial.js");
  const runtime = new library.Runtime();
  window.KESAR_PAGE_CLEANUP = () => runtime.cleanup();

  function choose(items) {
    return items[Math.floor(Math.random() * items.length)];
  }

  async function run() {
    try {
      const changed = await runtime.changedCoordinates();
      const changedKeys = new Set(changed.map(library.key));
      const unchanged = [];
      for (let x = -2; x <= 2; x += 1) {
        for (let z = 2; z >= -2; z -= 1) {
          const coordinate = { x, z };
          if (!changedKeys.has(library.key(coordinate))) unchanged.push(coordinate);
        }
      }

      const mode = document.getElementById("ask_about_changed_cell").value;
      let highlighted;
      let isChanged = false;
      if (mode === "true" && changed.length) {
        highlighted = choose(changed);
        isChanged = true;
      } else if (mode === "false" && unchanged.length) {
        highlighted = choose(unchanged);
      } else if (mode === "random" && changed.length && Math.random() < 0.5) {
        highlighted = choose(changed);
        isChanged = true;
      } else if (unchanged.length) {
        highlighted = choose(unchanged);
      } else {
        highlighted = choose(changed);
        isChanged = true;
      }
      if (!highlighted) throw new Error("No valid highlighted location");
      document.getElementById("highlighted_cell").value = JSON.stringify(highlighted);
      document.getElementById("highlighted_cell_changed").value = isChanged ? "1" : "0";
      runtime.showGrid("Judge the marble landing in the highlighted square", null, highlighted);
      await runtime.sleep(2000);
      await runtime.playPair();
      if (runtime.destroyed) return;

      runtime.showChoices(
        "Compared with the first marble, the highlighted marble in the second video was…",
        [
          { label: "← Lighter", value: 0, keys: ["ArrowLeft"] },
          { label: "The Same", value: 1, keys: ["ArrowUp", "ArrowDown"] },
          { label: "Heavier →", value: 2, keys: ["ArrowRight"] },
        ],
        (choice, duration) => {
          if (runtime.submitted) return;
          document.getElementById("perception").value = String(choice);
          document.getElementById("time_perception").value = String(duration);
          const difference = library.massCode(runtime.video2) - library.massCode(runtime.video1);
          const correct = isChanged
            ? ((difference > 0 && choice === 2) || (difference < 0 && choice === 0))
            : choice === 1;
          document.getElementById("perception_correct").value = correct ? "1" : "0";
          runtime.submit();
        }
      );
    } catch (error) {
      runtime.fail(error);
    }
  }

  run();
})();
