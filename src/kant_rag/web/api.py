"""웹 채팅 화면용 API — 기존 엔진(KnowledgeAgent·MCQSolver)을 그대로 호출하고 화면용 JSON 으로만 바꾼다.

검색·판정·프롬프트 로직은 건드리지 않는다. 요청마다 설정을 복사해 '답변 모델'만 바꿀 수 있다
(평가 CLI 는 이 모듈을 쓰지 않으므로 평가 조건은 그대로).

실행: uv run kant-rag-web            (기본 http://127.0.0.1:8600)
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from urllib.parse import quote as urlquote

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kant_rag.config import ROOT, Settings, get_settings

WEB_DIR = ROOT / "app" / "web"
CIRCLED = "①②③④⑤"

MODES = [
    {"id": "hybrid_rerank", "label": "정확도 우선", "desc": "키워드 + 의미 검색 후 다시 순위 매기기 (기본)"},
    {"id": "hybrid", "label": "빠르게", "desc": "키워드 + 의미 검색 (다시 순위 매기기 생략)"},
    {"id": "vector", "label": "의미 검색만", "desc": "비교 실험용"},
]
PRESET_DESC = {
    "v2": "기본 풀이 · 가장 빠름",
    "v5": "리라이트·인용 대조",
    "v6": "연결 근거·재검색",
    "v6r": "v6 + 반대 근거 확인·다수결",
    "v6r2": "v6r + 근거 적합성·인용-결론 일치 (가장 정밀, 느림)",
}
STATUS_KIND = {
    "ok": "ok", "tie": "ok", "inconsistent_judgments": "ok", "invalid_citation": "ok",
    "insufficient_evidence": "insufficient",
    "retrieval_error": "error", "generation_error": "error",
}


# ---------------------------------------------------------------- 엔진 (지연 생성, 한 번에 하나씩)
class Engine:
    def __init__(self) -> None:
        self.base: Settings = get_settings()
        self._retriever = None
        self._agents: dict = {}
        self._solvers: dict = {}
        self.lock = threading.Lock()  # GPU 검색·리랭커를 한 번에 하나만

    @property
    def retriever(self):
        if self._retriever is None:
            from kant_rag.retrieval.pipeline import Retriever

            self._retriever = Retriever(self.base)
        return self._retriever

    def settings_for(self, model_id: str | None) -> Settings:
        s = self.base.model_copy(deep=True)
        opt = next((m for m in model_options(self.base) if m["id"] == model_id), None)
        if opt is not None:
            s.models.llm_provider, s.models.llm_model = opt["provider"], opt["model"]
        return s

    def agent(self, model_id: str | None):
        from kant_rag.agent import KnowledgeAgent

        key = model_id or "default"
        if key not in self._agents:
            self._agents[key] = KnowledgeAgent(self.settings_for(model_id), retriever=self.retriever)
        return self._agents[key]

    def solver(self, model_id: str | None, preset: str):
        from kant_rag.mcq.presets import PRESETS, apply_overrides
        from kant_rag.mcq.solver import MCQSolver

        key = (model_id or "default", preset)
        if key not in self._solvers:
            s = apply_overrides(self.settings_for(model_id), PRESETS.get(preset, {}))
            self._solvers[key] = MCQSolver(s, self.retriever)
        return self._solvers[key]

    def chunk(self, cid: str):
        return self.retriever.vector.chunks_by_id.get(cid)

    @property
    def graph(self):
        """판결요지 조각을 항목 전체로 합쳐 보여주기 위한 관계 지도 (풀이 로직과 같은 ChunkGraph)."""
        if getattr(self, "_graph", None) is None:
            from kant_rag.mcq.context import ChunkGraph

            self._graph = ChunkGraph(self.retriever.vector.chunks_by_id)
        return self._graph

    @property
    def refs(self) -> tuple[dict, dict]:
        """(법령명, '제N조[의M]') → 조문 청크 id, 사건번호 → 판례 청크 id. 질문에 적힌 조문·사건번호를 바로 찾기 위한 색인."""
        if getattr(self, "_refs", None) is None:
            arts: dict = {}
            cases: dict = {}
            for cid, c in self.retriever.vector.chunks_by_id.items():
                md = c.metadata or {}
                if md.get("doc_type") == "statute" and md.get("article"):
                    arts.setdefault((re.sub(r"\s", "", c.title), md["article"]), []).append(cid)
                elif md.get("doc_type") == "case" and md.get("case_no"):
                    cases.setdefault(re.sub(r"\s", "", md["case_no"]).split(",")[0], []).append(cid)
            self._refs = (arts, cases)
        return self._refs

    def ask(self, model_id: str | None, question: str, mode) -> dict:
        """화면용 질의응답. 엔진 함수(쿼리 리라이트·검색·답변 생성)를 그대로 쓰되 화면에서만 다음을 보강한다
        (평가 CLI 의 KnowledgeAgent 경로와 설정은 그대로):
          1) 원질문 + 리라이트 질의를 둘 다 검색해 RRF 로 합침 (짧은 단어·비교 질문의 검색 누락 보완)
          2) 질문에 적힌 '법령명 제N조'·사건번호의 원문을 근거 맨 앞에 넣음 (예: 민법 제134조 → 민사소송법 제134조 오검색 방지)
          3) 리랭커 점수 문턱(rerank.min_score)으로 생성을 건너뛰지 않음 — 답할 수 있는지는 LLM 이 근거를 보고 판단
        """
        import time

        from kant_rag.generation.answer import generate_answer
        from kant_rag.optimize.rewrite import rewrite_query
        from kant_rag.retrieval.hybrid import rrf_fuse
        from kant_rag.schemas import RetrievedChunk

        s = self.settings_for(model_id)
        s.generation.max_context_chunks = max(s.generation.max_context_chunks, 8)
        s.generation.max_tokens = max(s.generation.max_tokens, 4000)  # 추론형 모델이 1024 토큰에서 잘려 JSON 이 깨지는 경우 방지
        t0 = time.perf_counter()
        query, rw = rewrite_query(question, s)
        t1 = time.perf_counter()
        finals = [self.retriever.retrieve(question, mode)["final"]]
        if query.strip() and query.strip() != question.strip():
            finals.append(self.retriever.retrieve(query, mode)["final"])
        fused = finals[0] if len(finals) == 1 else rrf_fuse(
            {f"q{i}": f for i, f in enumerate(finals)}, rrf_k=s.retrieval.rrf_k, top_k=s.retrieval.final_k)
        by_id = self.retriever.vector.chunks_by_id
        have = {r.chunk.chunk_id for r in fused}
        direct = [RetrievedChunk(chunk=by_id[c], score=1.0, rank=i + 1, source="rerank")
                  for i, c in enumerate(direct_refs(question, *self.refs)) if c not in have]
        ctx = [r.model_copy(update={"rank": i + 1}) for i, r in enumerate(direct + list(fused))]
        t2 = time.perf_counter()
        answer, info = generate_answer(question, ctx, s, min_rerank_score=None)
        if answer.status.value == "generation_error":  # 일시적인 호출·형식 오류는 한 번만 다시 시도
            answer, info = generate_answer(question, ctx, s, min_rerank_score=None)
        t3 = time.perf_counter()
        return {"answer": answer.model_dump(mode="json"), "models": s.models.model_dump(),
                "rewrite": rw, "direct_refs": [r.chunk.chunk_id for r in direct],
                "timing_ms": {"rewrite": round((t1 - t0) * 1000, 1), "retrieval": round((t2 - t1) * 1000, 1),
                              "generation": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)}}


ART_RE = re.compile(r"(?:([가-힣]+(?:법|규칙|법률|시행령))\s*)?제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
CASE_RE = re.compile(r"\d{2,4}\s*[가-힣]{1,3}\s*\d{1,7}")


def direct_refs(question: str, arts: dict, cases: dict, max_n: int = 4) -> list[str]:
    """질문에 적힌 '법령명 제N조(의M)'·사건번호 → 그 원문 청크 id (법령명이 없으면 민법). 없는 번호는 무시."""
    out: list[str] = []
    for m in ART_RE.finditer(question):
        law = re.sub(r"\s", "", m.group(1) or "민법")
        art = f"제{m.group(2)}조" + (f"의{m.group(3)}" if m.group(3) else "")
        out += [c for c in arts.get((law, art), [])[:2] if c not in out]
    for m in CASE_RE.finditer(question):
        out += [c for c in cases.get(re.sub(r"\s", "", m.group(0)), [])[:2] if c not in out]
    return out[:max_n]


ENGINE: Engine | None = None


def engine() -> Engine:
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine()
    return ENGINE


# ---------------------------------------------------------------- 설정
def model_options(base: Settings) -> list[dict]:
    """기본 모델(평가와 같은 설정) + WEB_MODEL_OPTIONS 의 추가 모델. 키가 서버에 없는 공급자는 뺀다."""
    default = {"id": f"{base.models.llm_provider}:{base.models.llm_model}", "provider": base.models.llm_provider,
               "model": base.models.llm_model, "label": base.models.llm_model, "default": True,
               "note": "기본 · 평가와 같은 모델"}
    out = [default]
    keys = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    for item in [x.strip() for x in os.getenv("WEB_MODEL_OPTIONS", "").split(",") if x.strip()]:
        provider, _, model = item.partition(":")
        if not model or item == default["id"]:
            continue
        if provider in keys and not os.getenv(keys[provider]):
            continue
        out.append({"id": item, "provider": provider, "model": model, "label": model, "default": False,
                    "note": "비교용 (평가 점수와 무관)"})
    return out


def _fmt_date(d: str | None) -> str | None:
    d = re.sub(r"\D", "", str(d or ""))
    return f"{d[:4]}. {int(d[4:6])}. {int(d[6:8])}." if len(d) == 8 else None


def doc_info(cid: str) -> dict | None:
    """청크 → 근거 패널용 정보. 원문에 있는 값만 쓴다 (사건번호·선고일·조문·출처)."""
    ch = engine().chunk(cid)
    if ch is None:
        return None
    md = ch.metadata or {}
    kind = md.get("doc_type") or ("case" if cid.startswith("CASE#") else "statute")
    text = ch.text
    if md.get("parent_id"):  # 판결요지 조각이면 항목 전체
        try:
            text = engine().graph.item_text(cid)
        except Exception:  # noqa: BLE001
            pass
    info = {"id": cid, "kind": kind, "title": ch.title, "location": ch.location(), "text": text,
            "source": md.get("source")}
    if kind == "case":
        info.update(case_no=md.get("case_no"), decided=_fmt_date(md.get("decided")))
        if md.get("prec_id"):
            info["url"] = f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={md['prec_id']}"
    else:
        art = md.get("article") or (cid.split("#")[1].split("~")[0].split("-")[0] if "#" in cid else None)
        info.update(article=art, article_title=md.get("article_title"), version=md.get("version"))
        if art and re.fullmatch(r"제\d+조(의\d+)?", art):
            info["url"] = f"https://www.law.go.kr/법령/{urlquote(ch.title)}/{urlquote(art)}"
    return info


# ---------------------------------------------------------------- 변환
def normalize_qa(rec: dict) -> dict:
    ans = rec.get("answer") or {}
    status = ans.get("status", "generation_error")
    ids = [c["chunk_id"] for c in ans.get("citations") or []]
    docs = {cid: d for cid in ids if (d := doc_info(cid))}
    text = ans.get("answer") or ""
    if text.startswith("제공된 문서에서 이 질문에 답할 근거를 찾지 못했습니다"):  # 엔진 고정 문구(업무 문서용)는 화면 안내로 대신
        text = ""
    kind = STATUS_KIND.get(status, "error")
    if kind == "insufficient" and text and any(c in docs for c in ids):
        kind = "partial"  # 모델이 '근거가 일부뿐'이라 표시했지만 확인된 범위의 답과 인용이 있음
    return {"type": "qa", "status": status, "status_kind": kind,
            "answer": text, "citations": [c for c in ids if c in docs], "docs": docs,
            "error": _safe_error(ans.get("error")) if STATUS_KIND.get(status) == "error" else None,
            "timing_ms": rec.get("timing_ms"), "model": (rec.get("models") or {}).get("llm_model")}


def normalize_mcq(q, rec: dict, preset: str) -> dict:
    sts = q.statements()
    single = not q.items
    js = rec.get("judgments") or {}
    qc = rec.get("quote_check") or {}
    statements, cited_all = [], []
    for k, text in sts.items():
        j = js.get(k) or {}
        v = j.get("verdict", "unknown")
        cited = [c for c in j.get("cited_chunk_ids") or []]
        cited_all += cited
        statements.append({
            "key": k, "label": CIRCLED[int(k) - 1] if single and k.isdigit() and 1 <= int(k) <= 5 else k,
            "text": text, "verdict": {"true": "O", "false": "X"}.get(v, "?"), "confidence": j.get("confidence"),
            "reason": j.get("reason"), "restated": j.get("restated"), "quote": j.get("quote"),
            "quote_verified": qc.get(k), "stance": j.get("stance"), "source": j.get("source"), "cited": cited,
        })
    docs = {cid: d for cid in dict.fromkeys(cited_all) if (d := doc_info(cid))}
    status = rec.get("status", "generation_error")
    pred = rec.get("predicted")
    return {
        "type": "mcq", "number": q.number, "form": q.form, "polarity": q.polarity, "stem": q.stem,
        "options": {str(n): t for n, t in q.options.items()},
        "statements": statements, "docs": docs,
        "option_scores": {str(n): v for n, v in (rec.get("option_scores") or {}).items()},
        "predicted": pred, "predicted_label": CIRCLED[pred - 1] if isinstance(pred, int) and 1 <= pred <= 5 else None,
        "predicted_text": q.options.get(pred) if isinstance(pred, int) else None,
        "status": status, "status_kind": STATUS_KIND.get(status, "error"),
        "error": _safe_error(rec.get("error")) if STATUS_KIND.get(status) == "error" else None,
        "research_changed": sorted(((rec.get("research") or {}).get("changed") or {}).keys()),
        "timing_ms": rec.get("timing_ms"), "model": (rec.get("models") or {}).get("llm_model"), "preset": preset,
    }


def _safe_error(err: str | None) -> str | None:
    """오류 문구에서 키처럼 보이는 값을 가린다 (화면 노출 방지)."""
    if not err:
        return err
    return re.sub(r"(sk-|sk_|key=)[A-Za-z0-9_\-]{6,}", r"\1***", str(err))[:400]


def looks_like_exam(text: str) -> bool:
    """보기 번호가 2개 이상 있으면 기출 문항으로 본다."""
    return len(set(re.findall(r"[①②③④⑤➀➁➂➃➄]", text))) >= 2


# ---------------------------------------------------------------- API
class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    model: str | None = None
    mode: str = "hybrid_rerank"
    preset: str | None = None
    intent: str = "auto"  # auto | ask | solve


app = FastAPI(title="민사법 판례 도우미 API", docs_url=None, redoc_url=None)


@app.get("/api/config")
def api_config() -> dict:
    from kant_rag.mcq.presets import PRESETS

    b = engine().base
    default_preset = b.default_preset if b.default_preset in PRESETS else "v5"
    asof = re.sub(r"\D", "", str(b.mcq.asof_default or b.retrieval.case_date_to or b.corpus.case_date_to or ""))
    return {
        "models": model_options(b),
        "modes": MODES,
        "presets": [{"id": p, "desc": PRESET_DESC.get(p, "")} for p in PRESETS if p in PRESET_DESC] or
                   [{"id": p, "desc": ""} for p in PRESETS],
        "default_preset": default_preset,
        "asof": _fmt_date(asof),
        "statute_snapshot": _fmt_date(b.corpus.statute_snapshot),
    }


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict:
    from kant_rag.retrieval.pipeline import RetrievalMode

    eng = engine()
    try:
        mode = RetrievalMode(body.mode)
    except ValueError:
        mode = RetrievalMode.C
    if mode == RetrievalMode.NONE:
        mode = RetrievalMode.C
    intent = body.intent if body.intent in ("ask", "solve") else ("solve" if looks_like_exam(body.text) else "ask")
    try:
        with eng.lock:
            if intent == "ask":
                return normalize_qa(eng.ask(body.model, body.text, mode))
            from kant_rag.mcq.textsolve import parse_pasted

            qs, problems = parse_pasted(body.text, id_prefix="WEB")
            if not qs:
                return {"type": "mcq_batch", "status_kind": "error", "items": [], "problems": problems,
                        "error": "문항을 인식하지 못했어요. 발문과 보기(①~⑤)가 모두 있는지 확인해 주세요."}
            preset = body.preset or eng.base.default_preset or "v5"
            solver = eng.solver(body.model, preset)
            items = [normalize_mcq(q, solver.solve(q, mode), preset) for q in qs[:5]]
            return {"type": "mcq_batch", "status_kind": "ok", "items": items, "problems": problems}
    except SystemExit as e:  # 엔진이 '색인 없음·임베딩 모델 불일치' 등 준비 문제로 종료 신호를 보냄 — 서버는 계속 띄워 둔다
        return {"type": "error", "status_kind": "error", "code": "setup",
                "error": _safe_error(str(e) or "검색 엔진을 준비하지 못했어요.")}
    except Exception as e:  # noqa: BLE001 — 시스템 오류는 '근거 없음'과 구분해 돌려준다
        return {"type": "error", "status_kind": "error", "error": _safe_error(f"{type(e).__name__}: {e}")}


# ---------------------------------------------------------------- 시험지 전체 풀이 (문항을 하나씩)
# 시험지를 한 번 해석해 두고(LLM 없음), 화면이 문항을 하나씩 요청한다 — 오래 걸리는 요청 하나 대신
# 문항마다 결과가 바로 쌓이고, 멈추기·이어 풀기가 된다. 정답은 채점용으로만 돌려주고 풀이 입력에서는 지운다.
BATCHES: dict[str, dict] = {}
MAX_BATCHES = 20


class ExamParseIn(BaseModel):
    text: str | None = Field(default=None, max_length=600_000)  # 시험지 텍스트 (문 1. / 【문 1】, ㄱ., ①~⑤)
    exam: dict | None = None  # 문항 JSON (kant-rag import-exam 형식: {exam, source, items})
    title: str | None = None


class ExamSolveIn(BaseModel):
    batch_id: str
    index: int
    model: str | None = None
    mode: str = "hybrid_rerank"
    preset: str | None = None


def _mode(name: str):
    from kant_rag.retrieval.pipeline import RetrievalMode

    try:
        m = RetrievalMode(name)
    except ValueError:
        return RetrievalMode.C
    return RetrievalMode.C if m == RetrievalMode.NONE else m


@app.post("/api/exam/parse")
def exam_parse(body: ExamParseIn) -> dict:
    """시험지 → 문항 목록 (LLM·검색 없음, 즉시)."""
    import time
    import uuid

    problems: list[str] = []
    title = body.title or "붙여 넣은 시험지"
    try:
        if body.exam is not None:
            from kant_rag.mcq.io import Exam

            ex = Exam.model_validate(body.exam)
            qs, title = list(ex.items), body.title or ex.exam
        elif body.text and body.text.strip():
            from kant_rag.mcq.textsolve import parse_pasted

            qs, problems = parse_pasted(body.text, id_prefix="WEB")
        else:
            qs = []
    except Exception as e:  # noqa: BLE001 — 형식이 다른 JSON 등
        return {"status_kind": "error", "error": _safe_error(f"시험지를 읽지 못했어요: {type(e).__name__}: {e}"), "questions": []}
    if not qs:
        return {"status_kind": "error", "questions": [], "problems": problems,
                "error": "문항을 찾지 못했어요. '문 1.' 같은 문항 번호와 보기(①~⑤)가 있는지 확인해 주세요."}
    bid = uuid.uuid4().hex[:12]
    BATCHES[bid] = {"questions": qs, "created": time.time()}
    for old in sorted(BATCHES, key=lambda k: BATCHES[k]["created"])[:-MAX_BATCHES]:
        BATCHES.pop(old, None)
    return {
        "status_kind": "ok", "batch_id": bid, "title": title, "problems": problems,
        "questions": [{"index": i, "number": q.number, "subject": q.subject, "form": q.form,
                       "stem": short_text(q.stem, 90), "answer": q.answer,
                       "accepted": sorted(set(q.accepted or []) | ({q.answer} if q.answer else set()))}
                      for i, q in enumerate(qs)],
    }


@app.post("/api/exam/solve")
def exam_solve(body: ExamSolveIn) -> dict:
    """해석해 둔 시험지의 문항 하나를 푼다. 서버가 다시 켜져 시험지가 없으면 code=expired (화면이 다시 해석)."""
    eng = engine()
    batch = BATCHES.get(body.batch_id)
    if batch is None:
        return {"status_kind": "error", "code": "expired", "error": "시험지 정보가 만료됐어요. 다시 불러올게요."}
    if not 0 <= body.index < len(batch["questions"]):
        return {"status_kind": "error", "error": "문항 번호가 범위를 벗어났어요."}
    q = batch["questions"][body.index]
    q_in = q.model_copy(update={"answer": None, "accepted": [], "statement_labels": {}, "evidence": []})  # 정답은 풀이에 넣지 않음
    preset = body.preset or eng.base.default_preset or "v5"
    try:
        with eng.lock:
            rec = eng.solver(body.model, preset).solve(q_in, _mode(body.mode))
        item = normalize_mcq(q_in, rec, preset)
    except SystemExit as e:
        return {"status_kind": "error", "code": "setup", "error": _safe_error(str(e) or "검색 엔진을 준비하지 못했어요.")}
    except Exception as e:  # noqa: BLE001
        item = {"type": "mcq", "number": q.number, "status": "generation_error", "status_kind": "error",
                "error": _safe_error(f"{type(e).__name__}: {e}"), "statements": [], "docs": {}}
    return {"status_kind": "ok", "index": body.index, "item": item}


def short_text(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


@app.get("/")
def index() -> FileResponse:
    # 화면을 고친 뒤에도 브라우저가 예전 index.html(예전 app.js 주소)을 쓰지 않도록 매번 확인하게 한다
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="kant-rag-web")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8600)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
