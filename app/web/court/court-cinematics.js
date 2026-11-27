"use strict";

const courtSession = {
  read(key) {
    try { return sessionStorage.getItem("kant-court-" + key); } catch { return null; }
  },
  write(key, value) {
    try { sessionStorage.setItem("kant-court-" + key, value); } catch { /* The current page still works. */ }
  },
};

const cinematicAssets = {
  closed: "court-door-closed.webp",
  open: "court-door-open.webp",
  chamber: "courtroom.webp",
  raised: "judge-gavel-raised.webp",
  strike: "judge-gavel-strike.webp",
};

function prepareCourtLink() {
  const link = document.getElementById("court-entry");
  if (!link) return;
  let leaving = false;
  let transition;
  let veil;
  link.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
        courtSession.read("intro-seen") || matchMedia("(prefers-reduced-motion: reduce)").matches || !Element.prototype.animate) return;
    event.preventDefault();
    if (leaving) return;
    leaving = true;
    veil = document.createElement("div");
    veil.style.cssText = "position:fixed;inset:0;z-index:9999;background:#100b08;pointer-events:none;";
    veil.setAttribute("aria-hidden", "true");
    document.body.append(veil);
    transition = veil.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: "ease-in", fill: "forwards" });
    transition.finished.then(() => location.assign(link.href), () => {});
  });
  window.addEventListener("pageshow", () => {
    leaving = false;
    transition?.cancel();
    veil?.remove();
  });
}

class CourtCinematics {
  constructor(layer, { audio, reduced, speed }) {
    this.layer = layer;
    this.frame = layer.querySelector(".cinematic-frame");
    this.description = layer.querySelector(".cinematic-description");
    this.skipButton = layer.querySelector(".cinematic-skip");
    this.controls = document.querySelectorAll(".game-header, .hud");
    this.audio = audio;
    this.reduced = reduced;
    this.speed = speed;
    this.images = new Map();
    this.skipButton.addEventListener("click", () => this.end("skip"));
    document.addEventListener("keydown", (event) => {
      if (this.active && event.key === "Escape") {
        event.preventDefault();
        this.end("skip");
      }
    });
  }

  get active() { return Boolean(this.run); }

  preload(names) {
    return Promise.all(names.map((name) => {
      if (!this.images.has(name)) {
        const image = new Image();
        image.alt = "";
        image.decoding = "async";
        if (name === "closed") image.fetchPriority = "high";
        image.src = "/static/court/assets/" + cinematicAssets[name];
        this.images.set(name, { image, ready: image.decode().then(() => true, () => false) });
      }
      return this.images.get(name).ready;
    }));
  }

  start(kind, done, prepare = null) {
    if (this.active) return false;
    if (this.reduced()) {
      done("reduced");
      return false;
    }
    const run = { kind, done, prepare, controller: new AbortController(), speed: this.speed() };
    this.run = run;
    this.focusBefore = document.activeElement;
    this.layer.dataset.kind = kind;
    this.frame.dataset.cue = "black";
    this.layer.hidden = false;
    for (const element of this.controls) element.inert = true;
    this.skipButton.focus({ preventScroll: true });
    const sequence = kind === "intro" ? this.intro(run) : this.verdict(run);
    sequence.then(() => {
      if (this.run === run) this.end("complete");
    }, () => {
      if (this.run === run) this.end("unavailable");
    });
    return true;
  }

  end(reason, resume = true) {
    const run = this.run;
    if (!run) return;
    this.run = null;
    run.controller.abort();
    this.audio.stopCinematic();
    this.layer.hidden = true;
    this.frame.replaceChildren();
    this.description.textContent = "";
    for (const element of this.controls) element.inert = false;
    if (resume) {
      this.focusBefore?.focus({ preventScroll: true });
      run.done(reason);
    }
    this.focusBefore = null;
  }

  pause(run, milliseconds) {
    return new Promise((resolve) => {
      const signal = run.controller.signal;
      if (signal.aborted) return resolve(false);
      const complete = (elapsed) => {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        resolve(elapsed);
      };
      const abort = () => complete(false);
      const timer = setTimeout(() => complete(true), milliseconds);
      signal.addEventListener("abort", abort, { once: true });
    });
  }

  async ready(run, names) {
    const assets = await Promise.race([
      this.preload(names),
      this.pause(run, 1000).then(() => null),
    ]);
    if (!assets?.every(Boolean) || this.run !== run) throw new Error("Cinematic images are unavailable.");
  }

  image(name, className = "") {
    const image = this.images.get(name).image.cloneNode();
    if (className) image.className = className;
    return image;
  }

  cue(run, cue, description, milliseconds) {
    const duration = milliseconds / run.speed;
    this.frame.style.setProperty("--cue-time", duration + "ms");
    this.frame.dataset.cue = cue;
    this.description.textContent = description;
    return this.pause(run, duration);
  }

  async intro(run) {
    await this.ready(run, ["closed", "open", "chamber"]);
    const doors = document.createElement("div");
    doors.className = "cine-doors";
    doors.append(this.image("closed"), this.image("open", "cine-open"));
    const light = document.createElement("i");
    light.className = "cine-door-light";
    doors.append(light);
    this.frame.append(doors);
    if (!await this.cue(run, "closed", "닫힌 법정 문", 860)) return;
    const opening = this.cue(run, "open", "법정 문이 열립니다.", 1150);
    this.audio.play("door", 0, run.speed);
    if (!await opening) return;
    const room = this.image("chamber", "cine-chamber");
    this.frame.append(room);
    if (!await this.cue(run, "chamber", "법정 안으로 들어갑니다.", 600)) return;
    const title = document.createElement("div");
    title.className = "cine-title";
    const name = document.createElement("span");
    name.textContent = "KANT COURT";
    name.lang = "en";
    const subtitle = document.createElement("p");
    subtitle.textContent = "판례와 조문으로 사건을 심리합니다.";
    title.append(name, subtitle);
    this.frame.append(title);
    if (!await this.cue(run, "title", "KANT COURT. 판례와 조문으로 사건을 심리합니다.", 1050)) return;
    run.prepare?.();
    await this.cue(run, "exit", "", 390);
  }

  async verdict(run) {
    await this.ready(run, ["raised", "strike"]);
    this.frame.append(this.image("raised", "cine-gavel"));
    if (!await this.cue(run, "raised", "재판장이 의사봉을 들어 올립니다.", 740)) return;
    await new Promise((resolve) => requestAnimationFrame(resolve));
    if (this.run !== run) return;
    this.frame.replaceChildren(this.image("strike", "cine-gavel"));
    const strike = this.cue(run, "strike", "판결을 선고합니다.", 1130);
    this.audio.play("gavel");
    if (!await strike) return;
    run.prepare?.();
    await this.cue(run, "exit", "", 300);
  }
}

prepareCourtLink();
