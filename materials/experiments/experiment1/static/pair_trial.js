(function () {
  const form = document.querySelector("form");
  const submit = document.getElementById("submit");
  const video = document.getElementById("trial-video");
  const stage = document.getElementById("trial-stage");
  const fixation = document.getElementById("fixation");
  const choiceScreen = document.getElementById("choice-screen");
  const question = document.getElementById("choice-question");
  const lighter = document.getElementById("lighter");
  const heavier = document.getElementById("heavier");
  const perception = document.getElementById("perception");
  const reactionTime = document.getElementById("reaction_time");
  const errorBox = document.getElementById("trial-error");
  const video1 = document.getElementById("video1_path");
  const video2 = document.getElementById("video2_path");
  if (!form || !submit || !video || !video1 || !video2) return;

  let destroyed = false;
  let submitted = false;
  let choiceStarted = 0;
  const timers = new Set();

  submit.style.display = "none";
  submit.disabled = true;
  video.hidden = true;
  stage.classList.add("blank");

  function sleep(milliseconds) {
    return new Promise((resolve) => {
      const id = window.setTimeout(() => {
        timers.delete(id);
        resolve();
      }, milliseconds);
      timers.add(id);
    });
  }

  async function blank(milliseconds) {
    if (destroyed) return;
    video.hidden = true;
    choiceScreen.hidden = true;
    fixation.hidden = true;
    stage.classList.add("blank");
    await sleep(milliseconds);
  }

  async function showFixation(milliseconds) {
    if (destroyed) return;
    fixation.hidden = false;
    await sleep(milliseconds);
    fixation.hidden = true;
  }

  function play(path) {
    return new Promise((resolve, reject) => {
      if (destroyed) return resolve();
      stage.classList.remove("blank");
      video.hidden = false;
      video.src = path;
      video.currentTime = 0;
      const done = () => {
        cleanupMediaListeners();
        resolve();
      };
      const failed = () => {
        cleanupMediaListeners();
        reject(new Error("Could not play " + path));
      };
      const cleanupMediaListeners = () => {
        video.removeEventListener("ended", done);
        video.removeEventListener("error", failed);
      };
      video.addEventListener("ended", done, { once: true });
      video.addEventListener("error", failed, { once: true });
      const promise = video.play();
      if (promise && typeof promise.catch === "function") promise.catch(failed);
    });
  }

  function finish(choice) {
    if (submitted || destroyed) return;
    submitted = true;
    perception.value = String(choice);
    reactionTime.value = String(Math.max(0, Math.round(performance.now() - choiceStarted)));
    submit.disabled = false;
    if (typeof form.requestSubmit === "function") form.requestSubmit(submit);
    else form.submit();
  }

  function onKeyDown(event) {
    if (choiceScreen.hidden) return;
    if (event.code === "ArrowLeft" || event.code === "ArrowRight") event.preventDefault();
    if (event.code === "ArrowLeft") finish(0);
    if (event.code === "ArrowRight") finish(1);
  }

  lighter.addEventListener("click", () => finish(0));
  heavier.addEventListener("click", () => finish(1));
  window.addEventListener("keydown", onKeyDown);

  async function run() {
    try {
      await blank(750);
      await showFixation(750);
      await play(video1.value);
      await blank(750);
      await play(video2.value);
      await blank(750);
      if (destroyed) return;
      stage.classList.remove("blank");
      const section = document.getElementById("trial_section").value;
      question.textContent = section === "multi"
        ? "Compared with the first group, the second group was…"
        : "Compared with the first object, the second object was…";
      choiceScreen.hidden = false;
      choiceStarted = performance.now();
    } catch (error) {
      errorBox.hidden = false;
      errorBox.textContent = "A stimulus could not be played. Check the local media bundle and reload this run.";
      console.error(error);
    }
  }

  window.KESAR_PAGE_CLEANUP = function () {
    destroyed = true;
    timers.forEach((id) => clearTimeout(id));
    timers.clear();
    window.removeEventListener("keydown", onKeyDown);
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch (error) {}
  };

  run();
})();
