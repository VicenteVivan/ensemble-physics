(function () {
  const library = window.ThingsStuffTrialRuntime;
  if (!library) throw new Error("trial_runtime.js must load before group_trial.js");
  const runtime = new library.Runtime();
  window.KESAR_PAGE_CLEANUP = () => runtime.cleanup();

  async function run() {
    try {
      const changed = await runtime.changedCoordinates();
      const changedKeys = new Set(changed.map(library.key));
      await runtime.playPair();
      if (runtime.destroyed) return;
      runtime.showChoices(
        "Compared with the first group, the second group was…",
        [
          { label: "← Lighter", value: 0, keys: ["ArrowLeft"] },
          { label: "Heavier →", value: 1, keys: ["ArrowRight"] },
        ],
        (choice, duration) => {
          if (runtime.choiceScreen.hidden) return;
          document.getElementById("perception").value = String(choice);
          document.getElementById("time_perception").value = String(duration);
          const difference = library.massCode(runtime.video2) - library.massCode(runtime.video1);
          const correct = (difference > 0 && choice === 1) || (difference < 0 && choice === 0);
          document.getElementById("perception_correct").value = correct ? "1" : "0";
          const gridStarted = performance.now();
          runtime.showGrid("Where did one changed marble land?", (coordinate) => {
            if (runtime.submitted || runtime.destroyed || runtime.failed) return;
            document.getElementById("grid_choice").value = JSON.stringify(coordinate);
            document.getElementById("grid_choice_correct").value = changedKeys.has(library.key(coordinate)) ? "1" : "0";
            document.getElementById("time_grid_choice").value = String(
              Math.max(0, Math.round(performance.now() - gridStarted))
            );
            runtime.submit();
          });
        }
      );
    } catch (error) {
      runtime.fail(error);
    }
  }

  run();
})();
