"use strict";

// The ambience and every cue are synthesized, so the game has no audio files to load.
class CourtAudio {
  constructor() {
    this.enabled = false;
    this.level = 0.35;
    this.cinematicSources = new Set();
    document.addEventListener("visibilitychange", () => this.updateGain());
  }

  async setEnabled(enabled) {
    this.enabled = enabled;
    if (!enabled) {
      this.updateGain();
      return;
    }
    if (!this.context) this.start();
    await this.context.resume();
    this.updateGain();
  }

  setVolume(level) {
    this.level = Math.max(0, Math.min(1, level));
    this.updateGain();
  }

  updateGain() {
    if (!this.context) return;
    const gain = this.enabled && !document.hidden ? this.level : 0;
    this.master.gain.setTargetAtTime(gain, this.context.currentTime, 0.04);
  }

  start() {
    const Context = window.AudioContext || window.webkitAudioContext;
    const context = this.context = new Context();
    this.master = context.createGain();
    this.master.gain.value = 0;
    this.master.connect(context.destination);

    this.noise = context.createBuffer(1, context.sampleRate * 4, context.sampleRate);
    const samples = this.noise.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = 2 * Math.random() - 1;

    const floor = context.createBufferSource();
    floor.buffer = this.noise;
    floor.loop = true;
    const air = context.createBiquadFilter();
    air.type = "bandpass";
    air.frequency.value = 310;
    air.Q.value = 0.51;
    const level = context.createGain();
    level.gain.value = 0.058;
    floor.connect(air).connect(level).connect(this.master);
    floor.start();
  }

  tone(time, from, to, level, duration, type = "sine") {
    const oscillator = this.context.createOscillator();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(from, time);
    oscillator.frequency.exponentialRampToValueAtTime(to, time + duration);
    oscillator.connect(this.envelope(time, level, duration));
    oscillator.start(time);
    oscillator.stop(time + duration + 0.01);
    return oscillator;
  }

  envelope(time, level, duration) {
    const gain = this.context.createGain();
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(level, time + 0.006);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + duration);
    gain.connect(this.master);
    return gain;
  }

  rustle(time, frequency, level, duration) {
    const source = this.context.createBufferSource();
    source.buffer = this.noise;
    const filter = this.context.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.value = frequency;
    filter.Q.value = 0.75;
    source.connect(filter).connect(this.envelope(time, level, duration));
    source.start(time, 0.25, duration);
    return source;
  }

  trackCinematic(...sources) {
    for (const source of sources) {
      this.cinematicSources.add(source);
      source.addEventListener("ended", () => this.cinematicSources.delete(source), { once: true });
    }
  }

  stopCinematic() {
    for (const source of this.cinematicSources) {
      try { source.stop(); } catch { /* The cue may already have ended. */ }
    }
    this.cinematicSources.clear();
  }

  play(effect, delay = 0, speed = 1) {
    if (!this.enabled || this.context?.state !== "running") return;
    const now = this.context.currentTime + delay;
    switch (effect) {
      case "gavel":
        this.trackCinematic(this.tone(now, 138, 52, 0.23, 0.24, "triangle"), this.rustle(now, 960, 0.18, 0.075));
        break;
      case "door":
        this.trackCinematic(
          this.rustle(now, 325, 0.108, 0.96 / speed),
          this.tone(now + 0.09 / speed, 123, 74, 0.034, 0.81 / speed, "triangle"),
          this.rustle(now + 0.49 / speed, 651, 0.076, 0.43 / speed),
        );
        break;
      case "hold":
        this.tone(now, 150, 94, 0.070, 0.28);
        this.rustle(now + 0.03, 570, 0.052, 0.23);
        break;
      case "paper":
        this.rustle(now, 1600, 0.096, 0.16);
        this.rustle(now + 0.075, 980, 0.067, 0.22);
        break;
      case "ui":
        this.tone(now, 480, 310, 0.028, 0.085);
        break;
    }
  }
}
