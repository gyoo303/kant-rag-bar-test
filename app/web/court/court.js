"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("case-form");
const question = byId("question");
const submit = byId("submit");
const game = byId("game");
const set = byId("set");
const dialogue = byId("dialogue-text");
const dialogueCopy = byId("dialogue-copy");
const caseDialog = byId("case-dialog");
const evidenceDialog = byId("evidence-dialog");
const verdictDialog = byId("verdict-dialog");
const logDialog = byId("log-dialog");
const optionsDialog = byId("options-dialog");
const previous = byId("previous");
const next = byId("next");
const nextLabel = byId("next-label");
const skip = byId("skip");
const auto = byId("auto");
const log = byId("log");
const fullscreen = byId("fullscreen");
const evidenceCue = byId("evidence-cue");
const ruling = byId("ruling");
const ballot = byId("ballot");
const submissionState = byId("submission-state");
const motion = byId("motion");
const sound = byId("sound");
const volume = byId("volume");
const audio = new CourtAudio();
const speed = byId("cinematic-speed");
const savedSpeed = courtSession.read("speed");
if ([...speed.options].some((option) => option.value === savedSpeed)) speed.value = savedSpeed;
const cinematics = new CourtCinematics(byId("cinematic"), { audio, reduced: motionIsReduced, speed: () => Number(speed.value) });
const record = byId("record-body");
const outcome = byId("outcome");
const state = byId("request-state");
const announcement = byId("scene-announcement");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const segmenter = Intl.Segmenter && new Intl.Segmenter("ko", { granularity: "sentence" });

const roles = {
  investigator: "판례 조사관",
  analyst: "법리 분석관",
  verifier: "법리 검증관",
  judge: "재판장",
};
const phases = {
  investigator: "증거 발표",
  analyst: "법리 분석",
  verifier: "근거 확인",
  judge: "판결 선고",
};
const outcomes = {
  ok: "판결 공개",
  partial: "일부 판단",
  insufficient: "판정 보류",
  error: "시스템 오류",
};

const shots = {};
const visited = new Set();
const welcome = "민사 법정에 오신 것을 환영합니다. 심리할 질문이나 기출 문항을 접수해 주세요.";
const demoExam = [
  "무권대리에 관한 설명 중 옳은 것을 모두 고른 것은?",
  "ㄱ. 본인이 추인하지 아니하면 본인에 대하여 효력이 없다.",
  "ㄴ. 계약 당시 상대방이 대리권이 없음을 알았던 경우에도 추인 전이면 철회할 수 있다.",
  "ㄷ. 본인이 추인하면 원칙적으로 계약을 한 때에 소급하여 효력이 생긴다.",
  "① ㄱ", "② ㄴ", "③ ㄱ, ㄴ", "④ ㄱ, ㄷ", "⑤ ㄱ, ㄴ, ㄷ",
].join("\n");
const optionLabels = "①②③④⑤";
let scenes = [];
let sceneIndex = -1;
let typingFrame = 0;
let autoTimer = 0;
let autoEnabled = false;
let shotRequest = 0;
let shotName = "courtroom";
let currentShot = set.querySelector(".shot");
let rulingPlayed = false;
let playerChoice = null;
let playerEvidence = null;
let requestPending = false;
let lastSubmittedQuestion = "";
let result = null;

function describe(text, limit = 220) {
  const line = String(text ?? "").replace(/^\s{0,3}#{1,6}\s+/gm, "").replaceAll("**", "").replace(/\s+/g, " ").trim();
  return line.length > limit ? line.slice(0, limit).trimEnd() + "…" : line;
}

function documentName(doc) {
  if (doc.kind === "case") return doc.case_no ? "대법원 " + doc.case_no : doc.title;
  return [doc.title, doc.article, doc.article_title].filter(Boolean).join(" ");
}

function finding(item) {
  if (item.status_kind === "error") return "error";
  if (item.status_kind === "insufficient" || item.status === "tie") return "insufficient";
  if (item.type === "mcq" && item.predicted == null) return "insufficient";
  if (item.type === "qa" && !item.answer) return "insufficient";
  if (item.status_kind === "partial" || ["inconsistent_judgments", "invalid_citation"].includes(item.status)) return "partial";
  return "ok";
}

function readResult(data) {
  if (data.type === "error" || data.status_kind === "error") throw new Error(data.error || "RAG 처리 중 오류가 발생했습니다.");
  if (data.type !== "qa" && (data.type !== "mcq_batch" || !data.items?.length)) {
    throw new Error("서버의 심리 결과를 읽을 수 없습니다.");
  }
  const items = data.type === "qa" ? [data] : data.items;
  const docs = Object.assign({}, ...items.map((item) => item.docs));
  const kinds = items.map(finding);
  const kind = kinds.every((value) => value === kinds[0]) ? kinds[0] : "partial";
  const failure = items.find((item) => item.error)?.error;
  return { items, docs, kind, failure };
}

function sentences(text) {
  return segmenter ? Array.from(segmenter.segment(text), (part) => part.segment) : text.split(/(?<=[.!?。])\s+/u);
}

function splitSpeech(text, limit = 115) {
  const cleaned = describe(text, Infinity);
  if (!cleaned) return [];
  const parts = [];
  let line = "";
  for (const part of sentences(cleaned)) {
    let sentence = part.trim();
    if (line && line.length + sentence.length + 1 > limit) {
      parts.push(line);
      line = "";
    }
    while (sentence.length > limit) {
      const space = sentence.lastIndexOf(" ", limit);
      const cut = space > limit / 2 ? space : limit;
      parts.push(sentence.slice(0, cut));
      sentence = sentence.slice(cut).trimStart();
    }
    line = [line, sentence].filter(Boolean).join(" ");
  }
  if (line) parts.push(line);
  return parts;
}

function makeScenes({ items, docs, kind }, questionText) {
  if (kind === "error") {
    return [{ role: "judge", text: "시스템 오류로 심리를 마치지 못했습니다. 심리 기록을 확인한 뒤 다시 시도해 주세요." }];
  }
  const first = items[0];
  const evidenceIds = Object.keys(docs);
  const cases = evidenceIds.filter((id) => docs[id].kind === "case").length;
  const citations = [cases && "판례 " + cases + "건", (evidenceIds.length - cases) && "조문 " + (evidenceIds.length - cases) + "개"]
    .filter(Boolean).join("과 ");
  const statements = items.flatMap((item) => item.statements || []);
  const checks = statements.filter((entry) => typeof entry.quote_verified === "boolean");
  const matched = checks.filter((entry) => entry.quote_verified).length;

  const script = [{
    role: "investigator",
    text: citations ? citations + "를 증거로 제출합니다." : "인용된 판례나 조문이 없어 제출할 증거가 없습니다.",
    evidence: evidenceIds,
  }];
  if (first.retrieval?.rewritten) {
    script.push({ role: "investigator", text: "검색에 사용한 보완 질의입니다. “" + describe(first.retrieval.rewritten, 91) + "”" });
  }

  if (first.type === "qa") {
    script.push({ role: "analyst", text: "심리할 쟁점입니다. “" + describe(first.retrieval?.query || questionText, 106) + "”" });
    const firstId = evidenceIds[0];
    if (firstId) {
      const doc = docs[firstId];
      const passage = evidenceHighlight(doc, firstId, items);
      const document = documentName(doc) || firstId;
      script.push({
        role: "analyst",
        text: passage ? document + "에서 인용한 자료입니다.\n“" + describe(passage, 98) + "”" : "이 쟁점에 대해 인용한 " + document + "를 확인해 주세요.",
        evidence: [firstId],
      });
    }
  } else {
    for (const item of items) {
      for (const entry of item.statements || []) {
        const label = (items.length > 1 ? item.number + "번 " : "") + entry.label;
        const verdict = entry.verdict === "?" ? "판정 보류" : entry.verdict;
        const heading = label + " 지문 · " + verdict;
        const lines = splitSpeech(entry.reason || entry.text, 112);
        const cited = (entry.cited || []).filter((id) => docs[id]);
        if (!lines.length) script.push({ role: "analyst", text: heading, evidence: cited });
        for (const line of lines) script.push({ role: "analyst", text: heading + "\n" + line, evidence: cited });
      }
    }
  }

  script.push({
    role: "verifier",
    text: checks.length
      ? "대조한 인용문 " + checks.length + "건 중 " + matched + "건이 원문과 일치했습니다." +
        (matched < checks.length ? "\n불일치 항목은 판결문의 지문별 기록에 표시했습니다." : "")
      : evidenceIds.length
        ? "증거 기록에서 인용 원문을 확인할 수 있습니다. 이번 응답에는 자동 원문 대조 결과가 포함되지 않았습니다."
        : "대조할 인용 원문이 없습니다.",
    evidence: evidenceIds,
  });

  if (items.length === 1 && first.type === "mcq") {
    const choices = Object.entries(first.options || {}).filter(([key, text]) => /^[1-5]$/.test(key) && typeof text === "string");
    if (choices.length >= 2) {
      script.push({
        role: "judge",
        kind: "ballot",
        text: "선고에 앞서, 어느 보기가 옳다고 판단하십니까?",
        choices,
        evidence: evidenceIds,
      });
    }
  }

  let verdict;
  if (kind === "insufficient") {
    verdict = first.status === "tie"
      ? "보기의 점수가 같아 최종 답을 확정할 수 없습니다."
      : "현재 제출된 근거만으로는 판단할 수 없습니다. 판정을 보류합니다.";
  } else if (first.type === "qa") {
    verdict = kind === "partial" ? "확인된 범위에서만 판단합니다. " + first.answer : first.answer;
  } else if (items.length === 1) {
    verdict = (kind === "partial" ? "풀이 결과에 확인이 필요한 항목이 있습니다. " : "") +
      "선택한 답은 " + (first.predicted_label || first.predicted) + "입니다.";
  } else {
    verdict = items.length + "문항의 심리를 마쳤습니다. 문항별 판정과 근거는 심리 기록에서 확인할 수 있습니다.";
  }

  if (kind === "ok") script.push({ role: "judge", kind: "close-hearing", text: "모든 증거와 법리 검토를 마쳤습니다." });
  const spokenVerdict = splitSpeech(verdict);
  for (const line of spokenVerdict.slice(0, 5)) script.push({ role: "judge", text: line });
  if (spokenVerdict.length > 5) script.push({ role: "judge", text: "판결문에서 답변 전체와 인용 원문을 확인할 수 있습니다." });
  return script;
}

function stopTyping(fullText) {
  cancelAnimationFrame(typingFrame);
  typingFrame = 0;
  if (fullText !== undefined) dialogue.textContent = fullText;
  game.dataset.lineReady = String(fullText !== undefined);
}

function motionIsReduced() {
  return reducedMotion.matches || motion.checked;
}

function scheduleAuto() {
  clearTimeout(autoTimer);
  const scene = scenes[sceneIndex];
  if (cinematics.active || !autoEnabled || !scene || scene.kind === "ballot" || typingFrame || sceneIndex >= scenes.length - 1 ||
      ruling.hidden === false || document.querySelector("dialog[open]")) return;
  autoTimer = setTimeout(advance, Math.max(1750, Math.min(5700, scene.text.length * 36)));
}

function typeDialogue(text, instant) {
  stopTyping();
  if (instant || motionIsReduced()) {
    stopTyping(text);
    scheduleAuto();
    return;
  }
  dialogue.textContent = "";
  const characters = Array.from(text);
  const startedAt = performance.now();
  let index = 0;
  let elapsed = 0;
  let written = "";
  function frame(time) {
    while (index < characters.length && elapsed <= time - startedAt) {
      const character = characters[index++];
      written += character;
      elapsed += /[.!?。…\n]/u.test(character) ? 112 : /[,·]/u.test(character) ? 63 : /\s/u.test(character) ? 12 : 23;
    }
    dialogue.textContent = written;
    if (index < characters.length) typingFrame = requestAnimationFrame(frame);
    else {
      stopTyping(text);
      scheduleAuto();
    }
  }
  typingFrame = requestAnimationFrame(frame);
}

function preloadShots() {
  for (const name of ["courtroom", ...Object.keys(roles)]) {
    if (shots[name]) continue;
    const image = new Image();
    image.alt = "";
    image.src = "/static/court/assets/" + name + ".webp";
    shots[name] = image;
  }
}

async function changeShot(name, instant = false) {
  const request = ++shotRequest;
  if (name === shotName) return;
  preloadShots();
  const art = name === "judgment" ? "judge" : name === "review" ? "analyst" : name;
  try {
    await shots[art].decode();
  } catch {
    return;
  }
  if (request !== shotRequest) return;

  for (const element of [...set.children]) {
    if (element !== currentShot) element.remove();
  }
  const oldShot = currentShot;
  const outgoingImage = oldShot.firstElementChild;
  outgoingImage.style.transform = getComputedStyle(outgoingImage).transform;
  const startingOpacity = getComputedStyle(oldShot).opacity;
  oldShot.classList.remove("is-current");
  const incoming = node("div", "", "shot is-current");
  incoming.dataset.shot = name;
  incoming.append(shots[art].cloneNode());
  set.append(incoming);
  currentShot = incoming;
  shotName = name;
  game.dataset.shot = name;
  if (motionIsReduced() || instant) {
    oldShot.remove();
    return;
  }
  oldShot.animate([{ opacity: startingOpacity }, { opacity: 0 }], { duration: 205, easing: "ease-in", fill: "forwards" });
  const animation = incoming.animate(
    [{ opacity: 0 }, { opacity: 0, offset: 0.36 }, { opacity: 1 }],
    { duration: 530, easing: "ease-out" },
  );
  animation.finished.then(() => oldShot.remove(), () => oldShot.remove());
}

function showHold() {
  audio.play("hold");
  if (motionIsReduced()) return;
  ruling.dataset.kind = "hold";
  byId("ruling-title").textContent = "판정을 보류합니다";
  ruling.hidden = false;
}

function renderBallot(scene) {
  ballot.hidden = scene.kind !== "ballot";
  if (ballot.hidden) return;
  ballot.replaceChildren();
  for (const [key, text] of scene.choices) {
    const option = node("button");
    option.type = "button";
    option.append(node("strong", optionLabels[Number(key) - 1]), node("span", text));
    option.dataset.choice = key;
    option.disabled = rulingPlayed;
    if (playerChoice === key) option.classList.add("is-chosen");
    option.addEventListener("click", () => submitChoice(key));
    ballot.append(option);
  }
}

function showScene(index, instant = false) {
  const scene = scenes[index];
  if (!scene) return;
  clearTimeout(autoTimer);
  ruling.hidden = true;
  const changedRole = scenes[sceneIndex]?.role !== scene.role;
  sceneIndex = index;
  visited.add(index);
  const choosing = scene.kind === "ballot";
  const closing = scene.kind === "close-hearing";
  const verdict = scene.role === "judge" && !scene.kind;
  const failed = result.kind === "error";
  game.dataset.state = failed ? "error" : choosing ? "ballot" : "playing";
  byId("speaker").textContent = roles[scene.role];
  changeShot(verdict && !failed ? "judgment" : scene.role, instant);
  byId("scene-phase").textContent = failed ? "심리 중단" : choosing ? "내 판단" : closing ? "심리 종료" : phases[scene.role];
  byId("ballot-keys").hidden = !choosing || rulingPlayed;
  byId("scene-step").textContent = failed ? "" : (index + 1) + " / " + scenes.length;
  announcement.textContent = roles[scene.role] + " · " + scene.text;
  next.disabled = false;
  dialogueCopy.disabled = failed;
  log.disabled = false;
  auto.disabled = failed || scenes.length < 2;
  previous.disabled = index === 0;
  skip.hidden = verdict || failed || choosing;
  byId("new-case").hidden = failed || !verdict;
  byId("open-verdict").hidden = !verdict || (!failed && index === scenes.length - 1);
  byId("open-verdict").textContent = failed ? "오류 상세" : "판결문";
  byId("key-hint").hidden = failed || choosing;
  nextLabel.textContent = failed ? "다시 시도" : choosing ? (rulingPlayed ? "선고 보기" : "선택 없이 선고")
    : closing ? "선고 진행" : index === scenes.length - 1 ? "판결문 열기" : "다음 대사";
  renderBallot(scene);

  const ids = scene.evidence || [];
  evidenceCue.hidden = !ids.length;
  if (ids.length) {
    byId("evidence-cue-label").textContent = ids.length === 1
      ? documentName(result.docs[ids[0]]) || "증거 열기"
      : "증거 열기 · " + ids.length + "건";
  }
  if (verdict && result.kind === "insufficient" && !rulingPlayed && !instant) showHold();
  else if (changedRole && !instant) audio.play("ui");
  if (verdict) rulingPlayed = true;
  typeDialogue(scene.text, instant);
  if (choosing && !instant && !document.querySelector("dialog[open]")) ballot.focus({ preventScroll: true });
}

function updateSubmissions() {
  const label = playerChoice ? "판단 " + optionLabels[Number(playerChoice) - 1] + " 제출됨" : "";
  submissionState.textContent = [playerEvidence ? "근거 제출됨" : "", label].filter(Boolean).join(" · ");
  submissionState.hidden = !submissionState.textContent;
  if (!submissionState.hidden) {
    submissionState.removeAttribute("data-stamped");
    void submissionState.offsetWidth;
    submissionState.setAttribute("data-stamped", "");
  }
}

function submitChoice(key) {
  const scene = scenes[sceneIndex];
  if (rulingPlayed || scene?.kind !== "ballot" || !scene.choices.some(([id]) => id === key)) return;
  playerChoice = key;
  updateSubmissions();
  audio.play("paper");
  showScene(sceneIndex + 1);
  next.focus({ preventScroll: true });
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function answerParagraph(text) {
  const paragraph = node("p");
  const words = text.replace(/^\s{0,3}#{1,6}\s+/gm, "").split(/(\*\*[^*]+\*\*)/g);
  words.forEach((part, index) => {
    if (index % 2) paragraph.append(node("strong", part.slice(2, -2)));
    else paragraph.append(part);
  });
  return paragraph;
}

function evidenceHighlight(doc, id, items) {
  if (!doc.text) return "";
  const quotes = items.flatMap((item) => item.statements || [])
    .filter((entry) => entry.quote_verified && entry.cited?.includes(id) && entry.quote && doc.text.includes(entry.quote))
    .map((entry) => entry.quote);
  if (quotes.length) return quotes.sort((a, b) => b.length - a.length)[0];
  const line = doc.text.split(/\r?\n/).map((part) => part.trim())
    .find((part) => part.length >= 28 && !part.startsWith("["));
  if (!line) return "";
  const sentence = sentences(line)[0].trim();
  if (sentence.length <= 170) return sentence;
  const cut = sentence.lastIndexOf(" ", 170);
  return sentence.slice(0, cut > 100 ? cut : 170);
}

function evidenceText(doc, id) {
  const body = node("p", "", "document-text");
  const highlighted = evidenceHighlight(doc, id, result.items);
  const text = doc.text || "";
  if (!highlighted) {
    body.textContent = text;
    return body;
  }
  const position = text.indexOf(highlighted);
  body.append(text.slice(0, position), node("mark", highlighted), text.slice(position + highlighted.length));
  return body;
}

function addEvidenceSubmission(container, paragraph, doc, id) {
  if (rulingPlayed || !doc.text?.trim()) return;
  const controls = node("div", "", "evidence-action");
  const give = node("button", "이 문장 제출");
  give.type = "button";
  const clear = node("button", "제출 취소", "evidence-clear");
  clear.type = "button";
  const feedback = node("p", "", "document-meta");
  feedback.setAttribute("role", "status");
  function refresh() {
    const submitted = playerEvidence?.id === id;
    clear.hidden = !submitted;
    give.textContent = submitted ? "이 문장 다시 제출" : "이 문장 제출";
    feedback.textContent = submitted ? "내 근거로 제출했습니다. 판결문에서 대조할 수 있습니다."
      : "원문에서 문장을 선택하거나 표시된 문장을 제출하세요.";
  }

  function selectedPassage() {
    const selection = window.getSelection();
    if (!selection?.rangeCount || !paragraph.contains(selection.getRangeAt(0).commonAncestorContainer)) return "";
    return selection.toString().trim();
  }
  let chosenText = "";
  give.addEventListener("pointerdown", () => { chosenText = selectedPassage(); });
  give.addEventListener("click", () => {
    const excerpt = chosenText || selectedPassage() || evidenceHighlight(doc, id, result.items) || doc.text.trim().slice(0, 170);
    chosenText = "";
    if (excerpt.length > 240 || !paragraph.textContent.includes(excerpt)) {
      feedback.textContent = "원문 안에서 240자 이하의 문장을 골라 주세요.";
      return;
    }
    playerEvidence = { id, excerpt };
    updateSubmissions();
    audio.play("paper");
    refresh();
  });
  clear.addEventListener("click", () => {
    playerEvidence = null;
    updateSubmissions();
    refresh();
    give.focus({ preventScroll: true });
  });
  refresh();
  controls.append(give, clear, feedback);
  container.append(controls);
}

function sourceLink(doc) {
  if (typeof doc.url !== "string" || !doc.url.startsWith("https://www.law.go.kr/")) return null;
  const link = node("a", "국가법령정보센터에서 원문 보기");
  link.href = doc.url;
  link.target = "_blank";
  link.rel = "noopener";
  return link;
}

function openEvidence(ids, selected = ids[0]) {
  const body = byId("evidence-body");
  const doc = result?.docs[selected];
  if (!doc) return;
  body.replaceChildren();
  byId("evidence-title").textContent = documentName(doc) || doc.id;
  if (ids.length > 1) {
    const list = node("ul", "", "evidence-list");
    list.setAttribute("aria-label", "인용 근거 목록");
    for (const id of ids) {
      const row = node("li");
      const button = node("button", documentName(result.docs[id]) || id);
      button.type = "button";
      if (id === selected) {
        button.classList.add("is-selected");
        button.setAttribute("aria-current", "true");
      }
      button.addEventListener("click", () => {
        openEvidence(ids, id);
        body.querySelector(".is-selected")?.focus();
      });
      row.append(button);
      list.append(row);
    }
    body.append(list);
  }
  const where = [doc.kind === "case" ? "판례" : "조문", doc.decided, doc.location].filter(Boolean).join(" · ");
  const paragraph = evidenceText(doc, selected);
  body.append(node("p", where, "document-meta"), paragraph);
  addEvidenceSubmission(body, paragraph, doc, selected);
  const link = sourceLink(doc);
  if (link) body.append(link);
  audio.play("paper");
  openDialog(evidenceDialog);
}

function renderPlayerRecord(items, docs) {
  if (!playerChoice && !playerEvidence) return;
  const panel = node("section", "", "player-record");
  panel.append(node("h3", "내 판단과 근거"));
  if (playerChoice) {
    const item = items[0];
    const comparable = ["ok", "partial"].includes(finding(item)) && item.predicted != null;
    const submitted = optionLabels[Number(playerChoice) - 1];
    const official = comparable ? (item.predicted_label || String(item.predicted)) : "판정 보류";
    const comparisons = node("dl", "", "choice-comparison");
    for (const [title, value] of [["내 선택", submitted], ["재판부 판단", official]]) {
      const row = node("div");
      row.append(node("dt", title), node("dd", value));
      comparisons.append(row);
    }
    panel.append(comparisons);
    if (comparable) {
      panel.append(node("p", String(item.predicted) === playerChoice ? "재판부와 판단이 일치했습니다."
        : "재판부와 다른 판단을 냈습니다. 지문별 판단 이유를 펼쳐 볼 수 있습니다.", "record-note"));
    }
  }
  if (playerEvidence) {
    const { id, excerpt } = playerEvidence;
    panel.append(node("p", "내가 제출한 문장 · " + (documentName(docs[id]) || id), "record-note"), node("blockquote", excerpt));
    const verified = items.flatMap((item) => item.statements || [])
      .filter((entry) => entry.quote_verified && entry.quote && entry.cited?.includes(id))
      .map((entry) => entry.quote);
    const normalize = (text) => text.replace(/\s+/g, "").replace(/[“”‘’]/g, "");
    const matching = verified.find((quote) => normalize(excerpt).includes(normalize(quote)));
    if (matching || verified.length) {
      panel.append(node("p", matching ? "제출한 문장에 재판부가 대조한 인용문이 포함됩니다."
        : "같은 자료에서 재판부는 다음 문장을 대조했습니다.", "record-note"), node("blockquote", matching || verified[0]));
    } else {
      panel.append(node("p", "이 자료에 대해 재판부가 따로 대조한 인용문은 표시되지 않았습니다.", "record-note"));
    }
  }
  record.append(panel);
}

function renderRecord() {
  const { kind, items, docs, failure } = result;
  record.replaceChildren();
  outcome.textContent = outcomes[kind];
  outcome.dataset.kind = kind;
  outcome.hidden = false;

  if (kind === "error") {
    record.append(node("p", failure || "검색이나 답변 생성 중 문제가 발생했습니다. 다시 시도해 주세요.", "record-note"));
    return;
  }
  if (kind === "partial") {
    record.append(node("p", "확인된 범위의 판단을 표시합니다. 근거와 함께 확인하세요.", "record-note"));
  } else if (kind === "insufficient") {
    record.append(node("p", "현재 근거로는 답을 확정하기 어려워 판정을 보류했습니다.", "record-note"));
  }
  const first = items[0];
  const singleSelection = items.length === 1 && first.type === "mcq" &&
    ["ok", "partial"].includes(finding(first)) && first.predicted != null;
  if (singleSelection) {
    const lead = node("section", "", "verdict-answer");
    const title = node("h3", "선택 ");
    title.append(node("strong", first.predicted_label || String(first.predicted)));
    lead.append(title);
    if (first.predicted_text) lead.append(node("p", first.predicted_text));
    record.append(lead);
  }
  renderPlayerRecord(items, docs);

  const ids = Object.keys(docs);
  for (const item of items) {
    if (item.type === "qa") {
      if (item.answer) {
        const answer = node("div", "", "answer");
        for (const paragraph of item.answer.trim().split(/\n\s*\n/)) answer.append(answerParagraph(paragraph));
        record.append(answer);
      }
      continue;
    }
    const itemKind = finding(item);
    const heading = items.length > 1 ? item.number + "번 · " : "";
    const predicted = item.predicted_label || item.predicted;
    if (!singleSelection) {
      record.append(node("h3", heading + (predicted && ["ok", "partial"].includes(itemKind) ? "선택 " + predicted : outcomes[itemKind])));
      if (predicted && item.predicted_text) record.append(node("p", item.predicted_text));
    }
    if (itemKind === "partial") record.append(node("p", "지문별 판정 또는 인용에 확인이 필요합니다.", "record-note"));
    if (itemKind === "error") record.append(node("p", item.error || "문항 처리 중 오류가 발생했습니다.", "record-note"));
    for (const entry of item.statements || []) {
      const details = node("details");
      details.append(node("summary", entry.label + " · " + (entry.verdict === "?" ? "판정 보류" : entry.verdict) + " · " + describe(entry.text, 100)));
      if (entry.text) details.append(node("p", entry.text, "document-text"));
      if (entry.reason) details.append(node("p", entry.reason, "document-text"));
      if (entry.quote) details.append(node("p", "인용문 · " + entry.quote, "document-text"));
      if (typeof entry.quote_verified === "boolean") {
        details.append(node("p", "원문 대조 · " + (entry.quote_verified ? "일치" : "불일치"), "document-meta"));
      }
      const cited = (entry.cited || []).filter((id) => docs[id]).map((id) => "[" + (ids.indexOf(id) + 1) + "] " + documentName(docs[id]));
      if (cited.length) details.append(node("p", "근거 · " + cited.join(" / "), "document-meta"));
      record.append(details);
    }
  }

  if (!ids.length) return;
  record.append(node("h3", "근거 자료 · " + ids.length + "건"));
  for (const [index, id] of ids.entries()) {
    const open = node("button", "[" + (index + 1) + "] " + (documentName(docs[id]) || id) + " ↗", "open-document");
    open.type = "button";
    open.addEventListener("click", () => openEvidence(ids, id));
    record.append(open);
  }
}

function openDialog(dialog) {
  clearTimeout(autoTimer);
  if (!dialog.open) dialog.showModal();
}

function openCase() {
  if (cinematics.active) return;
  state.textContent = "";
  preloadShots();
  if (game.dataset.state === "opening") {
    introduceJudge(true);
  }
  openDialog(caseDialog);
}

function openVerdict() {
  if (!result || cinematics.active) return;
  ruling.hidden = true;
  if (typingFrame) stopTyping(scenes[sceneIndex].text);
  byId("record-title").textContent = result.kind === "error" ? "심리 중단" : "판결문";
  renderRecord();
  audio.play("paper");
  openDialog(verdictDialog);
}

function advance() {
  if (requestPending || cinematics.active) return;
  if (sceneIndex < 0 || result.kind === "error") {
    openCase();
  } else if (typingFrame) {
    stopTyping(scenes[sceneIndex].text);
    scheduleAuto();
  } else if (scenes[sceneIndex].kind === "ballot") {
    ballot.focus({ preventScroll: true });
  } else if (scenes[sceneIndex].kind === "close-hearing" && !rulingPlayed) {
    const resultIndex = sceneIndex + 1;
    clearTimeout(autoTimer);
    cinematics.start("verdict", () => {
      showScene(resultIndex, true);
      next.focus({ preventScroll: true });
    }, () => changeShot("judgment", true));
  } else if (sceneIndex === scenes.length - 1) {
    openVerdict();
  } else {
    showScene(sceneIndex + 1);
  }
}

function revealVerdict() {
  if (cinematics.active) return;
  const first = scenes.findIndex((scene) => scene.role === "judge" && !scene.kind);
  if (first === -1) return;
  showScene(first, true);
  next.focus({ preventScroll: true });
}

previous.addEventListener("click", () => showScene(sceneIndex - 1));
next.addEventListener("click", () => {
  if (scenes[sceneIndex]?.kind === "ballot") {
    showScene(sceneIndex + 1);
    next.focus({ preventScroll: true });
  } else {
    advance();
  }
});
dialogueCopy.addEventListener("click", advance);
skip.addEventListener("click", revealVerdict);
byId("new-case").addEventListener("click", () => {
  if (question.value.trim() === lastSubmittedQuestion) question.value = "";
  openCase();
});
byId("open-verdict").addEventListener("click", openVerdict);
byId("options").addEventListener("click", () => openDialog(optionsDialog));
evidenceCue.addEventListener("click", () => {
  openEvidence(scenes[sceneIndex].evidence);
});
auto.addEventListener("click", () => {
  autoEnabled = !autoEnabled;
  auto.setAttribute("aria-pressed", String(autoEnabled));
  scheduleAuto();
});
log.addEventListener("click", () => {
  const transcript = byId("transcript");
  transcript.replaceChildren();
  for (const index of [...visited].sort((a, b) => a - b)) {
    const scene = scenes[index];
    const item = node("li");
    const jump = node("button");
    jump.type = "button";
    jump.append(node("strong", roles[scene.role]), scene.text);
    if (scene.kind === "ballot" && playerChoice) jump.append("\n내 판단 · " + optionLabels[Number(playerChoice) - 1]);
    jump.addEventListener("click", () => {
      logDialog.close();
      showScene(index, true);
      next.focus({ preventScroll: true });
    });
    item.append(jump);
    transcript.append(item);
  }
  openDialog(logDialog);
});
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", scheduleAuto);
}
window.addEventListener("keydown", (event) => {
  if (cinematics.active || document.querySelector("dialog[open]")) return;
  if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
  if (scenes[sceneIndex]?.kind === "ballot" && /^[1-5]$/.test(event.key)) {
    event.preventDefault();
    submitChoice(event.key);
    return;
  }
  if (event.code !== "Space" ||
      event.target.closest?.("button, a, input, textarea, select, [contenteditable]")) return;
  event.preventDefault();
  advance();
});
ruling.addEventListener("animationend", (event) => {
  if (event.target !== ruling) return;
  ruling.hidden = true;
  scheduleAuto();
});

function syncMotion() {
  game.dataset.reduced = document.documentElement.dataset.reduced = String(motionIsReduced());
  if (!motionIsReduced()) return;
  cinematics.end("reduced");
  set.style.removeProperty("--parallax-x");
  set.style.removeProperty("--parallax-y");
  ruling.hidden = true;
  if (typingFrame && scenes[sceneIndex]) stopTyping(scenes[sceneIndex].text);
  scheduleAuto();
}
motion.addEventListener("change", syncMotion);
reducedMotion.addEventListener("change", syncMotion);
syncMotion();

sound.disabled = !window.AudioContext && !window.webkitAudioContext;
sound.addEventListener("change", async () => {
  try {
    await audio.setEnabled(sound.checked);
    if (sound.checked) audio.play("ui");
  } catch {
    sound.checked = false;
    await audio.setEnabled(false);
  }
});
volume.addEventListener("input", () => {
  byId("volume-value").textContent = volume.value + "%";
  audio.setVolume(Number(volume.value) / 100);
  courtSession.write("volume", volume.value);
});
const savedVolume = courtSession.read("volume");
if (savedVolume !== null && Number.isFinite(Number(savedVolume))) {
  volume.value = savedVolume;
  byId("volume-value").textContent = volume.value + "%";
  audio.setVolume(Number(volume.value) / 100);
}
speed.addEventListener("change", () => courtSession.write("speed", speed.value));
byId("replay-intro").addEventListener("click", () => {
  optionsDialog.close();
  clearTimeout(autoTimer);
  cinematics.start("intro", scheduleAuto);
});

fullscreen.hidden = !document.fullscreenEnabled;
fullscreen.addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    announcement.textContent = "브라우저에서 전체 화면을 전환할 수 없습니다.";
  }
});
document.addEventListener("fullscreenchange", () => {
  const label = document.fullscreenElement ? "전체 화면 종료" : "전체 화면";
  fullscreen.setAttribute("aria-label", label);
  fullscreen.title = label;
});

const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
let parallaxFrame = 0;
let parallaxX = 0;
let parallaxY = 0;
game.addEventListener("pointermove", (event) => {
  if (motionIsReduced() || !finePointer.matches) return;
  parallaxX = (event.clientX / game.clientWidth - 0.5) * 12;
  parallaxY = (event.clientY / game.clientHeight - 0.5) * 7;
  if (parallaxFrame) return;
  parallaxFrame = requestAnimationFrame(() => {
    parallaxFrame = 0;
    if (motionIsReduced()) return;
    set.style.setProperty("--parallax-x", parallaxX.toFixed(2) + "px");
    set.style.setProperty("--parallax-y", parallaxY.toFixed(2) + "px");
  });
});
game.addEventListener("pointerleave", () => {
  cancelAnimationFrame(parallaxFrame);
  parallaxFrame = 0;
  set.style.removeProperty("--parallax-x");
  set.style.removeProperty("--parallax-y");
});

function introduceJudge(instant) {
  changeShot("judge", instant);
  typeDialogue(welcome, instant);
  announcement.textContent = "재판장 · " + welcome;
}

function restoreCase() {
  let saved;
  try { saved = JSON.parse(courtSession.read("case")); } catch { return false; }
  if (!saved?.result || !Array.isArray(saved.result.items)) return false;
  result = saved.result;
  lastSubmittedQuestion = saved.question || "";
  question.value = saved.draft ?? lastSubmittedQuestion;
  scenes = makeScenes(result, lastSubmittedQuestion);
  for (const index of saved.visited || []) if (scenes[index]) visited.add(index);
  playerChoice = saved.choice ?? null;
  playerEvidence = saved.evidence && result.docs[saved.evidence.id] ? saved.evidence : null;
  rulingPlayed = Boolean(saved.rulingPlayed);
  updateSubmissions();
  showScene(scenes[saved.index] ? saved.index : 0, true);
  return true;
}

window.addEventListener("pagehide", () => {
  if (result && sceneIndex >= 0) {
    courtSession.write("case", JSON.stringify({
      result, index: sceneIndex, visited: [...visited], rulingPlayed, question: lastSubmittedQuestion,
      draft: question.value, choice: playerChoice, evidence: playerEvidence,
    }));
  }
  cinematics.end("exit", false);
  clearTimeout(autoTimer);
  audio.stopCinematic();
  audio.setEnabled(false);
  sound.checked = false;
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && sceneIndex < 0 && !requestPending && game.dataset.state === "opening") introduceJudge(true);
  if (event.persisted) scheduleAuto();
});

if (!restoreCase()) {
  if (courtSession.read("intro-seen") || motionIsReduced()) introduceJudge(true);
  else cinematics.start("intro", (reason) => {
    courtSession.write("intro-seen", "1");
    introduceJudge(reason !== "complete");
    if (reason === "skip") openCase();
  }, () => changeShot("judge", true));
}
preloadShots();
cinematics.preload(["raised", "strike"]);

for (const example of document.querySelectorAll("[data-example]")) {
  example.addEventListener("click", () => {
    question.value = example.dataset.example;
    question.focus();
  });
}
byId("demo-case").addEventListener("click", () => {
  question.value = demoExam;
  question.focus();
  question.setSelectionRange(0, 0);
  question.scrollTop = 0;
  audio.play("paper");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = question.value.trim();
  if (requestPending) return;
  if (!text) {
    state.textContent = "심리할 질문이나 문항을 입력해 주세요.";
    question.focus();
    return;
  }

  requestPending = true;
  lastSubmittedQuestion = text;
  submit.disabled = true;
  result = null;
  scenes = [];
  sceneIndex = -1;
  visited.clear();
  rulingPlayed = false;
  playerChoice = playerEvidence = null;
  updateSubmissions();
  ballot.hidden = true;
  ruling.hidden = true;
  caseDialog.close();
  changeShot("review");
  game.dataset.state = "pending";
  byId("speaker").textContent = roles.analyst;
  byId("scene-phase").textContent = "심리 대기";
  byId("scene-step").textContent = "";
  const pendingText = "사건이 접수되었습니다. 결과가 도착하면 증거부터 살펴보겠습니다.";
  stopTyping(pendingText);
  announcement.textContent = pendingText;
  dialogueCopy.disabled = next.disabled = log.disabled = previous.disabled = auto.disabled = true;
  skip.hidden = evidenceCue.hidden = byId("new-case").hidden = byId("open-verdict").hidden = byId("key-hint").hidden = true;
  byId("ballot-keys").hidden = true;
  nextLabel.textContent = "심리 중";
  const start = performance.now();
  const clock = setInterval(() => {
    byId("scene-step").textContent = Math.floor((performance.now() - start) / 1000) + "초";
  }, 1000);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 300000);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("웹 서버가 요청을 처리하지 못했습니다. HTTP " + response.status);
    result = readResult(await response.json());
  } catch (error) {
    const failure = error.name === "AbortError"
      ? "응답 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
      : error instanceof TypeError
        ? "RAG 서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요."
        : error.message;
    result = { kind: "error", items: [], docs: {}, failure };
  } finally {
    clearInterval(clock);
    clearTimeout(timeout);
    submit.disabled = false;
    requestPending = false;
  }
  scenes = makeScenes(result, text);
  showScene(0, result.kind === "error");
  if (!document.querySelector("dialog[open]")) next.focus({ preventScroll: true });
});
