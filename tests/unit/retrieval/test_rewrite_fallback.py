"""TKT-BE-M3-04: 쿼리 리라이트·C+R (AC-10-1·2·3, INV-10). 대역 모델, 실제 OpenAI 없음."""

from __future__ import annotations

import httpx
import openai
import pytest

from lawqa.retrieval.application.retrieval_service import RetrievalService
from lawqa.retrieval.domain.errors import RewriteFailedError
from lawqa.retrieval.domain.models import (
    Candidate,
    ExamItem,
    OptionQuery,
    RetrievalConfig,
    RetrievalMode,
)
from lawqa.retrieval.infrastructure.rewriter import (
    QUERY_MAX_CHARS,
    REWRITE_SCHEMA,
    OpenAIQueryRewriter,
    RewritePrompt,
    merge_rewrites,
)

ITEM = ExamItem(
    stem="甲이 乙과 매매계약을 해제한 경우에 관한 설명으로 옳은 것은?",
    options=("원상회복", "손해배상", "제3자 보호", "이자 가산", "동시이행"),
)
PARAMS = {"n_vec": 20, "n_bm25": 20, "n_fuse": 20, "k_opt": 4, "rrf_c": 60, "weights": (0.5, 0.5)}
C_R = RetrievalConfig(name="C+R", mode=RetrievalMode.C, use_rewrite=True, **PARAMS)
C = RetrievalConfig(name="C", mode=RetrievalMode.C, use_rewrite=False, **PARAMS)


class Recording:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[Candidate]:
        self.queries.append(query)
        return [Candidate(f"d{len(self.queries)}", "d", "loc", "t", final_rank=1)]


class _Chain:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error = result, error
        self.inputs: list = []

    def invoke(self, messages):
        self.inputs.append(messages)
        if self.error:
            raise self.error
        return self.result


class _Chat:
    def __init__(self, chain: _Chain) -> None:
        self.chain = chain

    def with_structured_output(self, schema, **kwargs):
        assert schema is REWRITE_SCHEMA and kwargs["method"] == "json_schema"
        return self.chain


def _rewriter(result=None, error=None) -> tuple[OpenAIQueryRewriter, _Chain]:
    chain = _Chain(result, error)
    return OpenAIQueryRewriter(_Chat(chain), RewritePrompt.load()), chain  # type: ignore[arg-type]


def _queries(**by_no: str) -> dict:
    return {"queries": [{"option_no": int(k[1:]), "query": v} for k, v in by_no.items()]}


ALL = _queries(
    o1="민법 제548조 원상회복",
    o2="해제와 손해배상 제551조",
    o3="제548조 제1항 단서 제3자",
    o4="원상회복 이자 제548조 제2항",
    o5="해제 동시이행 제549조",
)


# ── AC-10-1: 원문항과 변환 질의가 모두 기록, 검색 질의 = 변환 질의 ──
def test_c_plus_r_searches_rewritten_queries_and_keeps_originals():
    rewriter, _ = _rewriter(ALL)
    retriever = Recording()
    result = RetrievalService(retriever_for=lambda c: retriever, rewriter=rewriter).retrieve(
        ITEM, C_R
    )

    assert retriever.queries == [q["query"] for q in ALL["queries"]]
    first = result.options[0].query
    assert first.original.startswith("甲이 乙과") and first.original.endswith("원상회복")
    assert first.rewritten == "민법 제548조 원상회복" and not first.fallback


def test_rewriter_not_called_for_other_configs():
    rewriter, chain = _rewriter(ALL)
    retriever = Recording()
    RetrievalService(retriever_for=lambda c: retriever, rewriter=rewriter).retrieve(ITEM, C)
    assert chain.inputs == []
    assert retriever.queries[0].startswith("甲이 乙과")


# ── AC-10-2: 실패하면 원문항으로 검색, fallback 표시 ──
@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
        openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
        ValueError("json parse"),
    ],
)
def test_whole_failure_falls_back_to_original_for_all_options(error):
    rewriter, _ = _rewriter(error=error)
    retriever = Recording()
    result = RetrievalService(retriever_for=lambda c: retriever, rewriter=rewriter).retrieve(
        ITEM, C_R
    )

    assert all(o.query.fallback and o.query.rewritten is None for o in result.options)
    assert retriever.queries == [o.query.original for o in result.options]
    assert len(result.options) == 5  # 결과는 정상으로 나옴(INV-10)


@pytest.mark.parametrize("bad", [None, {"queries": "x"}, {"other": []}])
def test_malformed_output_raises_rewrite_failed(bad):
    rewriter, _ = _rewriter(bad)
    with pytest.raises(RewriteFailedError):
        rewriter.rewrite(ITEM, [OptionQuery(1, "q")])


def test_missing_empty_or_too_long_option_falls_back_only_that_option():
    partial = _queries(o1="민법 제548조", o3="  ", o4="가" * (QUERY_MAX_CHARS + 1), o5="제549조")
    rewriter, _ = _rewriter(partial)
    retriever = Recording()
    result = RetrievalService(retriever_for=lambda c: retriever, rewriter=rewriter).retrieve(
        ITEM, C_R
    )

    flags = [(o.query.option_no, o.query.fallback) for o in result.options]
    assert flags == [(1, False), (2, True), (3, True), (4, True), (5, False)]
    assert retriever.queries[0] == "민법 제548조"
    assert retriever.queries[1] == result.options[1].query.original


def test_merge_keeps_first_duplicate_and_ignores_unknown_numbers():
    queries = [OptionQuery(n, f"원{n}") for n in range(1, 6)]
    merged = merge_rewrites(queries, {1: "a", 9: "zz"})
    assert merged[0].rewritten == "a"
    assert [q.fallback for q in merged] == [False, True, True, True, True]


# ── AC-10-3: 리라이터 입력에 평가 데이터가 없음 ──
def test_rewriter_input_contains_only_stem_and_options():
    rewriter, chain = _rewriter(ALL)
    rewriter.rewrite(ITEM, [OptionQuery(n, "q") for n in range(1, 6)])
    system, user = chain.inputs[0]
    text = system.content + user.content
    for forbidden in ("answer_key", "expected", "allowed_evidence", "key_facts", "정답표"):
        assert forbidden not in text
    assert ITEM.stem in user.content and "5. 동시이행" in user.content
    assert "판단하지 않습니다" in system.content
    assert len(rewriter.prompt_sha) == 64
