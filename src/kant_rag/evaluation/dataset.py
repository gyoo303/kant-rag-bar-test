"""평가셋 스키마 (eval/dev.json, eval/test.json). 자세한 설명은 eval/README.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

QType = Literal["direct", "paraphrase", "no_answer"]  # 직접 검색 / 표현 변형·유사 조건 / 근거 없음


class EvidenceRef(BaseModel):
    doc_id: str
    chunk_id: str
    location: str  # 원문 위치 (예: "§ 2. 개봉 후 반품 / L8-9")
    statement: str | None = None  # 어느 지문의 근거인지 (선택형: "1"~"5", "ㄱ"~"ㅁ"). None 이면 문항 전체
    grade: Literal["decisive", "supporting"] = "decisive"  # 결정적(단독으로 판단 가능) / 보조
    note: str | None = None  # 라벨 근거 메모 (검색 누락, 라벨 확신도 등)


class EvalItem(BaseModel):
    id: str
    split: Literal["dev", "test"]
    type: QType
    question: str
    expected_facts: list[str] = Field(default_factory=list)  # 정답 충족 판정용 필수 핵심 사실
    reference_answer: str
    evidence: list[EvidenceRef] = Field(default_factory=list)  # 허용 근거 (하나라도 top-5 면 Hit)
    no_answer_reason: str | None = None  # 근거 없음 문항: 부재 판정 이유

    @model_validator(mode="after")
    def _check(self):
        if self.type == "no_answer":
            if self.evidence or not self.no_answer_reason:
                raise ValueError(f"{self.id}: 근거 없음 문항은 evidence 비움 + no_answer_reason 필수")
        elif not self.evidence or not self.expected_facts:
            raise ValueError(f"{self.id}: 답변 가능 문항은 evidence, expected_facts 필수")
        return self


class EvalSet(BaseModel):
    version: str
    split: Literal["dev", "test"]
    frozen: bool = False  # test 는 최종 실행 전에 true 로 고정
    items: list[EvalItem]

    @model_validator(mode="after")
    def _ids(self):
        ids = [i.id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("중복 질문 ID")
        if any(i.split != self.split for i in self.items):
            raise ValueError("split 불일치")
        return self


EXPECTED = {
    "dev": {"total": 10, "direct": None, "paraphrase": None, "answerable": 8, "no_answer": 2},
    "test": {"total": 20, "direct": 10, "paraphrase": 7, "answerable": 17, "no_answer": 3},
}


def load_evalset(path: Path) -> EvalSet:
    return EvalSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def check_composition(es: EvalSet) -> list[str]:
    """발제 요구 문항 구성(dev 8+2 / test 10+7+3)과 다르면 경고 목록을 반환."""
    exp = EXPECTED[es.split]
    n = {t: sum(i.type == t for i in es.items) for t in ("direct", "paraphrase", "no_answer")}
    got = {"total": len(es.items), "answerable": n["direct"] + n["paraphrase"], **n}
    return [f"{k}: 기대 {v}, 현재 {got[k]}" for k, v in exp.items() if v is not None and got[k] != v]
