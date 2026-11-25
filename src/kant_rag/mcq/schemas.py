"""변호사시험 선택형(객관식) 문항 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from kant_rag.evaluation.dataset import EvidenceRef

CIRCLED = "①②③④⑤"
Polarity = Literal["correct", "incorrect"]  # "옳은 것은?" / "옳지 않은 것은?"
Form = Literal["single", "combination", "ox", "count"]  # 보기 하나 / ㄱㄴㄷ 조합 / ○× 조합 / 옳은 것의 개수


class ExamQuestion(BaseModel):
    id: str  # 예: "BAR2026-CIV-012"
    number: int  # 시험지 문항 번호
    subject: str | None = None  # 민법 | 민사소송법 | 상법 ...
    stem: str  # 발문 (사례 지문 포함)
    items: dict[str, str] = Field(default_factory=dict)  # {"ㄱ": "...", "ㄴ": "..."} (조합/개수형)
    options: dict[int, str]  # {1: "...", ..., 5: "..."}
    answer: int | None = None  # 확정 정답 번호 (평가용, 풀이 입력에 절대 넣지 않음)
    # 평가 확장 필드 (선택): 진술별 정오, 허용 근거
    statement_labels: dict[str, bool] = Field(default_factory=dict)  # {"1": true, "ㄱ": false}
    evidence: list[EvidenceRef] = Field(default_factory=list)
    split: Literal["dev", "test", "extra"] | None = None
    type: Literal["direct", "paraphrase", "no_answer"] | None = None
    note: str | None = None  # 유형 분류 근거, 근거 표기 메모 등
    traps: list[str] = Field(default_factory=list)  # AI 함정 유형 (mcq/traps.py: 자동 + 팀 수동)

    @model_validator(mode="after")
    def _check(self):
        if sorted(self.options) != [1, 2, 3, 4, 5]:
            raise ValueError(f"{self.id}: 보기는 1~5 다섯 개여야 합니다")
        if self.answer is not None and self.answer not in self.options:
            raise ValueError(f"{self.id}: answer 범위 오류")
        return self

    @property
    def polarity(self) -> Polarity:
        neg = ("옳지 않은", "옳지않은", "틀린", "잘못된", "부적절한", "인정되지 않는", "해당하지 않는")
        return "incorrect" if any(k in self.stem for k in neg) else "correct"

    @property
    def form(self) -> Form:
        if self.items and all("(○)" in o or "(×)" in o for o in self.options.values()):
            return "ox"
        if self.items and ("몇 개" in self.stem or "개수" in self.stem):
            return "count"
        return "combination" if self.items else "single"

    def statements(self) -> dict[str, str]:
        """판단 대상 진술: 조합/개수형은 ㄱㄴㄷ…, 단일형은 보기 1~5."""
        return dict(self.items) if self.items else {str(k): v for k, v in self.options.items()}


class StatementJudgment(BaseModel):
    """LLM 출력: 진술 하나의 정오 판단."""

    verdict: Literal["true", "false", "unknown"]
    confidence: float = Field(ge=0, le=1, description="근거에 비춘 판단 확신도 (자기 보고값, 확률 아님)")
    reason: str
    cited_chunk_ids: list[str] = Field(default_factory=list)
    source: Literal["evidence", "knowledge"] = "evidence"  # knowledge = 근거 없이 모델 지식으로 채운 판단 (개선안 C)
    restated: str | None = None  # 판단 프롬프트 v4: 이중부정·우회 표현을 단순한 평서문으로 풀어 쓴 문장
    quote: str | None = None     # 판단 프롬프트 v5: 결정적 근거 문장 (인용 청크와 대조)


def derive_statement_labels(q: ExamQuestion) -> dict[str, bool]:
    """확정 정답 번호로부터 진술별 참/거짓을 역산 (개수형은 판단 불가 → 빈 dict).

    - 단일형: '옳은 것' 이면 정답 보기만 참·나머지 거짓, '옳지 않은 것' 이면 정답 보기만 거짓·나머지 참
    - 조합형: 정답 보기에 든 진술 = 발문이 찾는 쪽(옳은 것이면 참), 빠진 진술 = 반대
    - ○× 조합형: 정답 보기의 ○/× 그대로
    """
    from kant_rag.mcq.parse import parse_combo, parse_ox

    if q.answer is None:
        return {}
    target = q.polarity == "correct"
    if q.form == "single":
        return {str(n): (target if n == q.answer else not target) for n in q.options}
    if q.form == "combination":
        chosen = parse_combo(q.options[q.answer])
        return {k: (target if k in chosen else not target) for k in q.items}
    if q.form == "ox":
        return parse_ox(q.options[q.answer])
    return {}
