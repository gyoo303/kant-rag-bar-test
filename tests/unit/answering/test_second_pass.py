"""CR-019: 근거가 모자란 보기의 명제만 다시 찾아 한 번 더 답한다.

2차는 **근거 충족일 때만 채택한다** — 근거 없이 답만 바뀌는 것을 막는다.
"""

from __future__ import annotations

from lawqa.answering.application.answer_service import AnswerService
from lawqa.answering.domain.models import ModelAnswer, ModelOption, Outcome
from lawqa.retrieval.domain.errors import RetrievalFailedError
from lawqa.retrieval.domain.models import Candidate, OptionQuery, OptionResult, RetrievalResult

STEM = """채무인수에 관한 설명 중 옳지 않은 것을 모두 고른 것은?
ㄱ. 첫째 명제.
ㄴ. 둘째 명제.
ㄷ. 셋째 명제.
ㄹ. 넷째 명제."""
ITEM = {"stem": STEM, "options": ["ㄱ", "ㄴ, ㄹ", "ㄱ, ㄴ, ㄷ", "ㄱ, ㄷ, ㄹ", "ㄱ, ㄴ, ㄷ, ㄹ"]}


def _cand(n: int) -> Candidate:
    return Candidate(
        chunk_id=f"c{n}", doc_id=f"prec:{n}", location=f"위치{n}", text=f"본문{n}", final_rank=1
    )


def _result() -> RetrievalResult:
    return RetrievalResult(
        config_name="C",
        options=tuple(
            OptionResult(query=OptionQuery(no, f"질의{no}"), candidates=(_cand(no),))
            for no in range(1, 6)
        ),
    )


def _model(answer: int, sufficient: bool, cite: str, insufficient: set[int]) -> ModelAnswer:
    return ModelAnswer(
        answer=answer,
        sufficient=sufficient,
        options=tuple(
            ModelOption(
                no=n,
                verdict="insufficient" if n in insufficient else "correct",
                reason="r",
                citations=() if n in insufficient else (cite,),
            )
            for n in range(1, 6)
        ),
        raw_output="{}",
    )


class _Retrieval:
    def __init__(self, extra: list[Candidate] | None = None, fail: bool = False) -> None:
        self.extra = extra if extra is not None else [_cand(99)]
        self.fail = fail
        self.followups: list[str] = []

    def retrieve(self, item, config):
        return _result()

    def retrieve_for(self, queries, config):
        self.followups = [q.effective for q in queries]
        if self.fail:
            raise RetrievalFailedError("2차 실패")
        return list(self.extra)


class _Generator:
    prompt_sha = "sha"

    def __init__(self, answers: list[ModelAnswer]) -> None:
        self.answers = answers
        self.calls = 0

    def generate(self, item, context):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def _service(retrieval, generator):
    from lawqa.retrieval.domain.models import RetrievalConfig, RetrievalMode

    config = RetrievalConfig(
        name="C",
        mode=RetrievalMode.C,
        use_rewrite=False,
        n_vec=3,
        n_bm25=3,
        n_fuse=3,
        k_opt=2,
        rrf_c=60,
        weights=(0.5, 0.5),
    )
    return AnswerService(retrieval=retrieval, generator=generator, configs={"C": config})


def test_second_pass_runs_and_is_adopted_when_sufficient() -> None:
    retrieval = _Retrieval()
    gen = _Generator(
        [
            _model(1, False, "c1", insufficient={2}),  # 1차: 보기2 근거 부족
            _model(2, True, "c99", insufficient=set()),  # 2차: 근거 충족
        ]
    )

    env = _service(retrieval, gen).answer(ITEM, "C")

    assert gen.calls == 2
    assert env.answer.outcome is Outcome.ANSWERED
    assert env.answer.answer_no == 2 and env.answer.evidence_sufficient is True
    assert env.followup_added == 1 and env.followup_queries
    # 보기 ②가 가리키는 ㄴ·ㄹ만 다시 찾는다
    joined = " ".join(retrieval.followups)
    assert "둘째" in joined and "넷째" in joined and "첫째" not in joined


def test_second_pass_is_discarded_when_still_insufficient() -> None:
    """근거 없이 답만 바뀌면 1차를 그대로 둔다."""
    gen = _Generator(
        [
            _model(1, False, "c1", insufficient={2}),
            _model(4, False, "c99", insufficient={2}),
        ]
    )

    env = _service(_Retrieval(), gen).answer(ITEM, "C")

    assert gen.calls == 2
    assert env.answer.answer_no == 1 and env.answer.evidence_sufficient is False
    assert env.followup_added == 0 and env.followup_queries == ()


def test_no_second_pass_when_first_is_sufficient() -> None:
    gen = _Generator([_model(3, True, "c3", insufficient=set())])

    env = _service(_Retrieval(), gen).answer(ITEM, "C")

    assert gen.calls == 1 and env.followup_queries == ()


def test_second_pass_retrieval_failure_keeps_first_answer() -> None:
    gen = _Generator([_model(1, False, "c1", insufficient={2})])

    env = _service(_Retrieval(fail=True), gen).answer(ITEM, "C")

    assert gen.calls == 1  # 2차 생성까지 가지 않는다
    assert env.answer.answer_no == 1 and env.answer.outcome is Outcome.ANSWERED


def test_second_pass_skipped_when_it_adds_nothing_new() -> None:
    """2차 검색이 이미 가진 청크만 돌려주면 다시 생성하지 않는다."""
    gen = _Generator([_model(1, False, "c1", insufficient={2})])

    env = _service(_Retrieval(extra=[_cand(1)]), gen).answer(ITEM, "C")

    assert gen.calls == 1 and env.followup_added == 0
