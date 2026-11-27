"use strict";

// Start kant-rag-web, then run: node --test tests/court_interaction.cjs
// Set PLAYWRIGHT_MODULE or COURT_BROWSER_EXECUTABLE to use an existing Playwright/Chromium installation.
const assert = require("node:assert/strict");
const { after, before, test } = require("node:test");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const baseURL = process.env.KANT_COURT_BASE_URL || "http://127.0.0.1:8600";
const documentId = "LAW#130";
const quote = "본인이 이를 추인하지 아니하면 본인에 대하여 효력이 없다.";
const doc = {
  id: documentId,
  kind: "statute",
  title: "민법",
  article: "제130조",
  text: "[민법] 제130조\n" + quote,
  url: "https://www.law.go.kr/법령/민법/제130조",
};
const exam = {
  type: "mcq_batch",
  status_kind: "ok",
  items: [{
    type: "mcq", status: "ok", status_kind: "ok", number: 1, predicted: 4, predicted_label: "④",
    predicted_text: "ㄱ, ㄷ", options: { 1: "ㄱ", 2: "ㄴ", 3: "ㄱ, ㄴ", 4: "ㄱ, ㄷ", 5: "ㄱ, ㄴ, ㄷ" },
    statements: [{ label: "ㄱ", verdict: "O", text: "테스트 지문", reason: "테스트 근거", quote, quote_verified: true, cited: [documentId] }],
    docs: { [documentId]: doc },
  }],
};
const qa = {
  type: "qa", status: "ok", status_kind: "ok", answer: "첫 번째 판단입니다. 두 번째 판단입니다.",
  citations: [documentId], docs: { [documentId]: doc },
};
const insufficient = { type: "qa", status: "insufficient_evidence", status_kind: "insufficient", answer: "", docs: {} };
let browser;

before(async () => {
  browser = await chromium.launch({ headless: true, executablePath: process.env.COURT_BROWSER_EXECUTABLE });
});
after(async () => { await browser?.close(); });

async function visit(context, body, { reducedMotion = "reduce", delay = 0, viewport, intro = false } = {}) {
  const page = await browser.newPage({ baseURL, reducedMotion, viewport });
  context.after(() => page.close());
  const requests = [];
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  if (!intro) await page.addInitScript(() => sessionStorage.setItem("kant-court-intro-seen", "1"));
  await page.route("**/api/chat", async (route) => {
    assert.equal(route.request().method(), "POST");
    requests.push(route.request().postDataJSON());
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    await route.fulfill({ json: body });
  });
  await page.goto("/court");
  return { page, requests, failures };
}

const button = (page, name) => page.getByRole("button", { name, exact: true });
const state = (page) => page.locator("#game").getAttribute("data-state");

async function enterDemo(page) {
  await button(page, "사건 접수").click();
  await button(page, "무권대리 예제 사건").click();
  assert.match(await page.locator("#question").inputValue(), /무권대리[\s\S]+⑤/);
  await button(page, "심리 시작").click();
}

async function stepUntil(page, predicate) {
  for (let i = 0; i < 25; i++) {
    if (await predicate()) return;
    await page.locator("#next").press("Enter");
  }
  assert.fail("The expected courtroom scene was not reached.");
}

test("demo exam supports one request, evidence submission, and an optional locked ballot", { timeout: 35000 }, async (context) => {
  const { page, requests, failures } = await visit(context, exam, { delay: 1250 });
  await enterDemo(page);
  assert.equal(await state(page), "pending");
  await page.waitForFunction(() => document.getElementById("scene-step").textContent === "1초");
  await page.locator('.shot.is-current[data-shot="investigator"]').waitFor();
  await page.locator("#evidence-cue").click();
  assert.equal(await page.locator("#evidence-body mark").textContent(), quote);
  await button(page, "이 문장 제출").click();
  assert.match(await page.locator(".evidence-action [role=status]").textContent(), /제출했습니다/);
  await button(page, "제출 취소").click();
  await button(page, "이 문장 제출").click();
  await button(page, "증거 자료 닫기").click();
  assert.equal(await page.locator("#speaker").textContent(), "판례 조사관");
  assert.equal(await page.locator("#submission-state").textContent(), "근거 제출됨");

  await stepUntil(page, async () => await state(page) === "ballot");
  assert.equal(await page.locator("#ballot button").count(), 5);
  await page.locator("#auto").click();
  await new Promise((resolve) => setTimeout(resolve, 1900));
  assert.equal(await state(page), "ballot", "Autoplay must wait for the player.");
  await page.keyboard.press("4");
  await button(page, "선고 진행").click();
  await page.locator('.shot.is-current[data-shot="judgment"]').waitFor();
  await button(page, "판결문 열기").click();
  assert.equal(await page.locator(".choice-comparison dd").allTextContents().then((choices) => choices.join()), "④,④");
  assert.match(await page.locator(".player-record").textContent(), /판단이 일치했습니다/);
  assert.match(await page.locator(".player-record").textContent(), /재판부가 대조한 인용문이 포함됩니다/);
  assert.equal(requests.length, 1);
  await page.locator(".open-document").first().click();
  assert.equal(await button(page, "이 문장 제출").count(), 0);
  await button(page, "증거 자료 닫기").click();
  await button(page, "판결문 닫기").click();
  await page.locator("#previous").click();
  await page.locator("#previous").click();
  assert.equal(await page.locator("#ballot button:disabled").count(), 5);
  assert.equal(await page.locator("#ballot button.is-chosen").getAttribute("data-choice"), "4");
  assert.deepEqual(failures, []);
});

test("typing completes before advancing and direct skip preserves full RAG QA output", { timeout: 26000 }, async (context) => {
  const { page, requests, failures } = await visit(context, qa, { reducedMotion: "no-preference" });
  await button(page, "사건 접수").click();
  await button(page, "불법행위").click();
  await button(page, "심리 시작").click();
  await page.waitForFunction(() => document.getElementById("speaker").textContent === "판례 조사관");
  const step = await page.locator("#scene-step").textContent();
  assert.equal(await page.locator("#game").getAttribute("data-line-ready"), "false");
  await page.locator("#dialogue-copy").press("Enter");
  assert.equal(await page.locator("#scene-step").textContent(), step);
  assert.equal(await page.locator("#game").getAttribute("data-line-ready"), "true");
  await page.locator("#dialogue-copy").press("Enter");
  assert.notEqual(await page.locator("#scene-step").textContent(), step);
  await button(page, "판결로 건너뛰기").click();
  assert.equal(await page.locator("#ballot").isVisible(), false);
  assert.equal(await page.locator("#ruling").isVisible(), false);
  await button(page, "판결문 열기").click();
  assert.match(await page.locator(".answer").textContent(), /첫 번째 판단입니다. 두 번째 판단입니다./);
  assert.equal(requests.length, 1);
  assert.deepEqual(failures, []);
});

test("insufficient evidence uses its own ruling without offering exam choices", { timeout: 26000 }, async (context) => {
  const { page, failures } = await visit(context, insufficient, { reducedMotion: "no-preference" });
  await button(page, "사건 접수").click();
  await page.locator("#question").fill("근거가 없는 예시 질문");
  await button(page, "심리 시작").click();
  await page.waitForFunction(() => document.getElementById("speaker").textContent === "판례 조사관");
  await stepUntil(page, async () => await page.locator("#scene-phase").textContent() === "판결 선고");
  assert.equal(await page.locator("#ruling").getAttribute("data-kind"), "hold");
  assert.equal(await page.locator("#ruling-title").textContent(), "판정을 보류합니다");
  assert.equal(await page.locator("#ballot").isVisible(), false);
  await stepUntil(page, async () => await page.locator("#verdict-dialog").isVisible());
  assert.equal(await page.locator("#outcome").textContent(), "판정 보류");
  assert.deepEqual(failures, []);
});

test("mobile settings start muted and control volume and reduced motion", { timeout: 26000 }, async (context) => {
  const { page, failures } = await visit(context, qa, { reducedMotion: "no-preference", viewport: { width: 390, height: 844 } });
  await button(page, "설정").click();
  assert.equal(await page.locator("#sound").isChecked(), false);
  await page.locator("#volume").fill("57");
  assert.equal(await page.locator("#volume-value").textContent(), "57%");
  await page.locator("#motion").check();
  assert.equal(await page.locator("#game").getAttribute("data-reduced"), "true");
  if (await page.locator("#sound").isEnabled()) {
    await page.locator("#sound").check();
    await page.waitForFunction(() => audio.context?.state === "running" && audio.level === 0.57);
    await page.locator("#sound").uncheck();
    assert.equal(await page.evaluate(() => audio.enabled), false);
  }
  await button(page, "설정 닫기").click();
  assert.ok(await page.locator("#game").evaluate((element) => element.clientWidth === innerWidth));
  assert.deepEqual(failures, []);
});

test("skipping the ballot still opens the original ruling without a player grade", { timeout: 26000 }, async (context) => {
  const { page, requests, failures } = await visit(context, exam);
  await enterDemo(page);
  await page.locator("#skip").waitFor();
  await button(page, "판결로 건너뛰기").click();
  assert.equal(await page.locator("#ballot").isVisible(), false);
  assert.equal(await page.locator("#ruling").isVisible(), false);
  await button(page, "판결문 열기").click();
  assert.match(await page.locator("#record-body").textContent(), /선택 ④/);
  assert.equal(await page.locator(".player-record").count(), 0);
  assert.equal(requests.length, 1);
  assert.deepEqual(failures, []);
});

test("opening presents the two door frames and title once, with immediate skip on replay", { timeout: 27000 }, async (context) => {
  const { page, failures } = await visit(context, exam, { intro: true, reducedMotion: "no-preference" });
  for (const cue of ["closed", "open", "chamber", "title"]) {
    await page.locator('.cinematic-frame[data-cue="' + cue + '"]').waitFor();
  }
  assert.equal(await page.locator(".cine-title span").textContent(), "KANT COURT");
  await page.locator("#cinematic").waitFor({ state: "hidden" });
  await button(page, "사건 접수").waitFor();
  await page.getByRole("link", { name: /일반 모드/ }).click();
  await page.getByRole("link", { name: "법정 모드" }).click();
  await page.waitForURL("**/court");
  assert.equal(await page.locator("#cinematic").isVisible(), false);
  await button(page, "설정").click();
  await page.locator("#cinematic-speed").selectOption("1.35");
  await button(page, "입장 연출 다시 보기").click();
  await button(page, "연출 건너뛰기").click();
  await button(page, "사건 접수").waitFor();
  assert.equal(await page.locator("#cinematic").isVisible(), false);
  await page.reload();
  assert.equal(await page.locator("#cinematic-speed").inputValue(), "1.35");
  assert.deepEqual(failures, []);
});

test("the strike schedules one audio cue, reveals the API result, and restores it after leaving", { timeout: 35000 }, async (context) => {
  const { page, requests, failures } = await visit(context, exam, { reducedMotion: "no-preference" });
  await page.evaluate(() => {
    window.cinematicCues = [];
    const play = audio.play.bind(audio);
    audio.play = (effect, ...args) => {
      const cue = document.querySelector(".cinematic-frame").dataset.cue;
      if (effect === "gavel") window.cinematicCues.push({ effect, cue });
      return play(effect, ...args);
    };
  });
  await enterDemo(page);
  await page.locator("#skip").waitFor();
  await stepUntil(page, async () => await state(page) === "ballot");
  await page.keyboard.press("4");
  await stepUntil(page, async () => await page.locator("#cinematic").isVisible());
  await page.locator('.cinematic-frame[data-cue="raised"] img').waitFor();
  await page.locator('.cinematic-frame[data-cue="strike"] img').waitFor();
  assert.equal(await page.locator(".cine-title").count(), 0);
  assert.equal(await page.locator("#ruling").isVisible(), false);
  assert.deepEqual(await page.evaluate(() => window.cinematicCues), [{ effect: "gavel", cue: "strike" }]);
  await page.locator("#cinematic").waitFor({ state: "hidden" });
  await button(page, "판결문 열기").click();
  assert.match(await page.locator(".player-record").textContent(), /판단이 일치했습니다/);
  await button(page, "판결문 닫기").click();
  await page.getByRole("link", { name: /일반 모드/ }).click();
  await page.getByRole("link", { name: "법정 모드" }).click();
  await button(page, "판결문 열기").click();
  assert.match(await page.locator(".verdict-answer").textContent(), /선택 ④/);
  assert.equal(requests.length, 1);
  assert.deepEqual(failures, []);
});

test("skipping the first opening goes straight to case intake", { timeout: 27000 }, async (context) => {
  const { page, failures } = await visit(context, exam, { intro: true, reducedMotion: "no-preference" });
  await button(page, "연출 건너뛰기").click();
  await page.locator("#case-dialog").waitFor();
  assert.equal(await page.locator("#cinematic").isVisible(), false);
  assert.deepEqual(failures, []);
});
