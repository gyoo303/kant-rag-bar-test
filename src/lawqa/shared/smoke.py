"""시작 전 점검 `check smoke` (US-03, API-04, AC-03-1·2).

생성 1건·임베딩 1건 호출, GPU와 재정렬 1건 지연, 같은 질의의 BM25·벡터 점수를 따로 기록한다.
점검 하나가 실패해도 나머지는 계속 하고, 실패는 결과 파일에 오류로 남긴다(R-1과 같은 원칙).
결과 파일: `<results_dir>/smoke/<YYYY-MM-DD_HHMMSS>.json` (덮어쓰지 않는다). 비밀값은 넣지 않는다.

외부 라이브러리(LangChain·OpenAI·torch·kiwipiepy·rank_bm25)는 `LiveSmokeProbes` 안에서만,
쓸 때 import 한다. 시험은 같은 계약의 가짜 점검기(`SmokeProbes`)로 대신한다.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lawqa.shared.clock import Clock
from lawqa.shared.logging_setup import log_event
from lawqa.shared.settings import Settings

log = logging.getLogger(__name__)

# BM25·벡터 시험 질의와 문서: 커밋된 law_collector/data/statutes/민법.txt 의 조문 3개
# (법령 본문, 공개)
SAMPLE_QUERY = "부동산 점유취득시효가 완성되면 등기하여야 소유권을 취득하는가"
SAMPLE_DOCS: tuple[tuple[str, str], ...] = (
    (
        "민법 제186조",
        "제186조(부동산물권변동의 효력) 부동산에 관한 법률행위로 인한 물권의 득실변경은 "
        "등기하여야 그 효력이 생긴다.",
    ),
    (
        "민법 제245조 제1항",
        "제245조(점유로 인한 부동산소유권의 취득기간) ①20년간 소유의 의사로 평온, 공연하게 "
        "부동산을 점유하는 자는 등기함으로써 그 소유권을 취득한다.",
    ),
    (
        "민법 제750조",
        "제750조(불법행위의 내용) 고의 또는 과실로 인한 위법행위로 타인에게 손해를 가한 자는 "
        "그 손해를 배상할 책임이 있다.",
    ),
)
SCALE_NOTE = (
    "BM25 점수는 질의 단어가 문서에 얼마나 일치하는지 세는 값으로 0 이상이고 상한이 없다. "
    "벡터 점수는 임베딩의 코사인 유사도로 -1~1 범위다. 척도가 달라 두 점수를 그대로 더하거나 "
    "비교할 수 없으므로 결합은 순위 기반 RRF로 한다(REQ-052, ADR-009)."
)
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


class SmokeProbes(Protocol):
    """점검기 계약. 실제 구현은 `LiveSmokeProbes`, 시험은 가짜 구현."""

    def generation(self) -> dict[str, Any]: ...
    def embedding(self) -> dict[str, Any]: ...
    def gpu(self) -> dict[str, Any]: ...
    def rerank(self, query: str, docs: list[str]) -> dict[str, Any]: ...
    def bm25_scores(self, query: str, docs: list[str]) -> list[float]: ...
    def vector_scores(self, query: str, docs: list[str]) -> list[float]: ...


@dataclass(slots=True)
class SmokeCheck:
    name: str
    ok: bool
    latency_ms: int
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class SmokeReport:
    started_at: str
    config_name: str
    config_sha: str
    checks: list[SmokeCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def run_smoke(settings: Settings, probes: SmokeProbes, clock: Clock) -> SmokeReport:
    """점검을 모두 실행하고 보고서를 돌려준다(파일 쓰기는 `write_report`)."""
    docs = [text for _, text in SAMPLE_DOCS]
    checks = [
        _run("generation", probes.generation),
        _run("embedding", probes.embedding),
        _run("gpu", probes.gpu),
        _run("rerank", lambda: probes.rerank(SAMPLE_QUERY, docs)),
        _run("bm25", lambda: _ranked(probes.bm25_scores(SAMPLE_QUERY, docs))),
        _run("vector", lambda: _ranked(probes.vector_scores(SAMPLE_QUERY, docs))),
    ]
    checks.append(
        SmokeCheck(
            name="score_scales",
            ok=True,
            latency_ms=0,
            detail={"query": SAMPLE_QUERY, "note": SCALE_NOTE},
        )
    )
    return SmokeReport(
        started_at=clock.now().isoformat(timespec="seconds"),
        config_name=settings.config_name,
        config_sha=settings.config_sha,
        checks=checks,
    )


def write_report(report: SmokeReport, results_dir: Path, clock: Clock) -> Path:
    """`<results_dir>/smoke/<YYYY-MM-DD_HHMMSS>.json`에 쓴다. 같은 이름이 있으면 번호를 붙인다."""
    out_dir = results_dir / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = clock.now().strftime("%Y-%m-%d_%H%M%S")
    path = out_dir / f"{stem}.json"
    suffix = 1
    while path.exists():
        path = out_dir / f"{stem}-{suffix}.json"
        suffix += 1
    text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    path.write_text(_redact(text), encoding="utf-8")
    return path


def summary_lines(report: SmokeReport) -> list[str]:
    """명령줄에 보여 줄 요약."""
    lines = []
    for check in report.checks:
        mark = "OK " if check.ok else "ERR"
        line = f"[{mark}] {check.name} {check.latency_ms}ms"
        if check.error:
            line += f" — {check.error}"
        lines.append(line)
    return lines


def _run(name: str, action: Callable[[], dict[str, Any]]) -> SmokeCheck:
    started = time.perf_counter()
    try:
        detail = action()
    except Exception as exc:  # 점검 하나의 실패를 기록하고 다음 점검을 계속한다
        latency = _elapsed_ms(started)
        message = _redact(f"{type(exc).__name__}: {exc}")
        log.warning("smoke check failed: %s", name, exc_info=True)
        log_event(log, "smoke_check", name=name, ok=False, latency_ms=latency)
        return SmokeCheck(name=name, ok=False, latency_ms=latency, error=message)
    latency = _elapsed_ms(started)
    log_event(log, "smoke_check", name=name, ok=True, latency_ms=latency)
    return SmokeCheck(name=name, ok=True, latency_ms=latency, detail=detail)


def _ranked(scores: list[float]) -> dict[str, Any]:
    """문서별 점수를 내림차순 순위로 바꾼다(점수는 그대로 기록)."""
    if len(scores) != len(SAMPLE_DOCS):
        raise ValueError(f"점수 개수 {len(scores)}가 문서 수 {len(SAMPLE_DOCS)}와 다릅니다.")
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return {
        "query": SAMPLE_QUERY,
        "results": [
            {"rank": rank, "location": SAMPLE_DOCS[i][0], "score": round(float(scores[i]), 6)}
            for rank, i in enumerate(order, start=1)
        ],
    }


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub("sk-***", text)


class LiveSmokeProbes:
    """실제 OpenAI API·GPU·Kiwi·BM25로 점검한다. 무거운 라이브러리는 메서드 안에서 import."""

    _CONTENT_TAGS = frozenset({"NNG", "NNP", "NNB", "NR", "NP", "VV", "VA", "XR", "SL", "SN", "SH"})

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._embeddings: Any = None
        self._kiwi: Any = None

    def generation(self) -> dict[str, Any]:
        from langchain_openai import ChatOpenAI

        model = self._settings.models.generation
        chat = ChatOpenAI(
            model=model,
            api_key=self._settings.secrets.require("openai_api_key"),
            timeout=self._settings.timeouts.generation_s,
            max_retries=0,
        )
        reply = chat.invoke("다음 낱말을 그대로 한 번만 쓰세요: 민법")
        return {
            "model_requested": model,
            "model_reported": reply.response_metadata.get("model_name"),
            "reply_chars": len(str(reply.content)),
        }

    def embedding(self) -> dict[str, Any]:
        vector = self._embed(["민법 제1조"])[0]
        return {
            "model_requested": self._settings.models.embedding,
            "dimensions": len(vector),
            "dimensions_expected": self._settings.models.embedding_dim,
        }

    def gpu(self) -> dict[str, Any]:
        import torch

        available = torch.cuda.is_available()
        return {
            "torch_version": torch.__version__,
            "cuda_build": torch.version.cuda,
            "cuda_available": available,
            "device_name": torch.cuda.get_device_name(0) if available else None,
        }

    def rerank(self, query: str, docs: list[str]) -> dict[str, Any]:
        from langchain_community.cross_encoders import HuggingFaceCrossEncoder

        device = self._settings.models.reranker_device
        load_started = time.perf_counter()
        encoder = HuggingFaceCrossEncoder(
            model_name=self._settings.models.reranker, model_kwargs={"device": device}
        )
        load_ms = _elapsed_ms(load_started)
        encoder.score([(query, docs[0])])  # 첫 호출 준비(워밍업)는 지연에서 뺀다
        score_started = time.perf_counter()
        scores = encoder.score([(query, doc) for doc in docs])
        return {
            "model": self._settings.models.reranker,
            "device": device,
            "load_ms": load_ms,
            "pairs": len(docs),
            "score_ms": _elapsed_ms(score_started),
            "scores": [round(float(s), 6) for s in scores],
        }

    def bm25_scores(self, query: str, docs: list[str]) -> list[float]:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi([self._tokenize(doc) for doc in docs])
        return [float(s) for s in bm25.get_scores(self._tokenize(query))]

    def vector_scores(self, query: str, docs: list[str]) -> list[float]:
        vectors = self._embed([query, *docs])
        return [_cosine(vectors[0], v) for v in vectors[1:]]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings

            self._embeddings = OpenAIEmbeddings(
                model=self._settings.models.embedding,
                dimensions=self._settings.models.embedding_dim,
                api_key=self._settings.secrets.require("openai_api_key"),
                max_retries=0,
            )
        return self._embeddings.embed_documents(texts)

    def _tokenize(self, text: str) -> list[str]:
        if self._kiwi is None:
            from kiwipiepy import Kiwi

            self._kiwi = Kiwi()
        return [t.form for t in self._kiwi.tokenize(text) if t.tag in self._CONTENT_TAGS]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
