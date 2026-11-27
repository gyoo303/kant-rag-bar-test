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
    return {"type": "qa", "status": status, "status_kind": STATUS_KIND.get(status, "error"),
            "answer": ans.get("answer") or "", "citations": [c for c in ids if c in docs], "docs": docs,
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
    return re.sub(r"(sk-|sk_|key=)[A-Za-z0-9_\-]{6,}", r"\1***", str(err))[:300]


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
                return normalize_qa(eng.agent(body.model).ask(body.text, mode=mode))
            from kant_rag.mcq.textsolve import parse_pasted

            qs, problems = parse_pasted(body.text, id_prefix="WEB")
            if not qs:
                return {"type": "mcq_batch", "status_kind": "error", "items": [], "problems": problems,
                        "error": "문항을 인식하지 못했어요. 발문과 보기(①~⑤)가 모두 있는지 확인해 주세요."}
            preset = body.preset or eng.base.default_preset or "v5"
            solver = eng.solver(body.model, preset)
            items = [normalize_mcq(q, solver.solve(q, mode), preset) for q in qs[:5]]
            return {"type": "mcq_batch", "status_kind": "ok", "items": items, "problems": problems}
    except Exception as e:  # noqa: BLE001 — 시스템 오류는 '근거 없음'과 구분해 돌려준다
        return {"type": "error", "status_kind": "error", "error": _safe_error(f"{type(e).__name__}: {e}")}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


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
