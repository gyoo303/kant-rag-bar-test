"""변호사시험 선택형(객관식) 문항 스키마."""

from __future__ import annotations

import re

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from kant_rag.evaluation.dataset import EvidenceRef

CIRCLED = "①②③④⑤"
Polarity = Literal["correct", "incorrect"]  # "옳은 것은?" / "옳지 않은 것은?"
Form = Literal["single", "combination", "ox", "count", "blank"]  # 보기 하나 / ㄱㄴㄷ 조합 / ○× 조합 / 옳은 것의 개수 / 괄호 넣기


class ExamQuestion(BaseModel):
    id: str  # 예: "BAR2026-CIV-012"
    number: int  # 시험지 문항 번호
    subject: str | None = None  # 민법 | 민사소송법 | 상법 ...
    stem: str  # 발문 (사례 지문 포함)
    items: dict[str, str] = Field(default_factory=dict)  # {"ㄱ": "...", "ㄴ": "..."} (조합/개수형)
    options: dict[int, str]  # {1: "...", ..., 5: "..."}
    answer: int | None = None  # 확정 정답 번호 (평가용, 풀이 입력에 절대 넣지 않음)
    accepted: list[int] = Field(default_factory=list)  # 복수 정답 인정 (v6 0-3): 정답 CSV 의 "4|5". answer 도 포함
    # 평가 확장 필드 (선택): 진술별 정오, 허용 근거
    statement_labels: dict[str, bool] = Field(default_factory=dict)  # {"1": true, "ㄱ": false}
    evidence: list[EvidenceRef] = Field(default_factory=list)
    split: Literal["dev", "test", "extra"] | None = None
    type: Literal["direct", "paraphrase", "no_answer"] | None = None
    note: str | None = None  # 유형 분류 근거, 근거 표기 메모 등
    traps: list[str] = Field(default_factory=list)  # AI 함정 유형 (mcq/traps.py: 자동 + 팀 수동)
    # 괄호 넣기형: 보기 번호 → {빈칸: 값}, 빈칸 → 그 빈칸이 있는 진술 키
    blanks: dict[int, dict[str, str]] = Field(default_factory=dict)
    blank_items: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        if sorted(self.options) != [1, 2, 3, 4, 5]:
            raise ValueError(f"{self.id}: 보기는 1~5 다섯 개여야 합니다")
        if self.answer is not None and self.answer not in self.options:
            raise ValueError(f"{self.id}: answer 범위 오류")
        return self

    def is_correct(self, predicted: int | None) -> bool:
        """예측이 정답(또는 복수 정답 인정 번호)인가."""
        return predicted is not None and (predicted == self.answer or predicted in self.accepted)

    @property
    def polarity(self) -> Polarity:
        neg = ("옳지 않은", "옳지않은", "틀린", "잘못된", "부적절한", "인정되지 않는", "해당하지 않는")
        if any(k in self.stem for k in neg):
            return "incorrect"
        # '판례의 태도와 다른 것은?', '판례의 입장에 부합하지 않는 것은?' — 물음 문장에서만 본다 (사례 본문 오인 방지)
        ask = self.stem[max(0, self.stem.rfind("?", 0, len(self.stem)) - 120):] if "?" in self.stem else self.stem[-120:]
        neg_ask = ("다른 것", "부합하지 않는", "맞지 않는", "옳지 아니한", "어긋나는")
        return "incorrect" if any(k in ask for k in neg_ask) else "correct"

    @property
    def form(self) -> Form:
        if self.blanks:
            return "blank"
        if self.items and all("(○)" in o or "(×)" in o for o in self.options.values()):
            return "ox"
        count_opts = all(re.fullmatch(r"\s*\d+\s*개\s*", o or "") for o in self.options.values())
        if self.items and ("몇 개" in self.stem or "개수" in self.stem or "것의 수" in self.stem or count_opts):
            return "count"
        return "combination" if self.items else "single"

    def blank_candidates(self) -> dict[str, tuple[str, str]]:
        """괄호 넣기형: 후보 진술 키(A1, A2 …) → (빈칸, 값). 빈칸마다 보기에 나온 값의 순서대로."""
        out: dict[str, tuple[str, str]] = {}
        for letter in sorted(self.blank_items):
            seen: list[str] = []
            for n in sorted(self.blanks):
                v = self.blanks[n].get(letter)
                if v is not None and v not in seen:
                    seen.append(v)
            for i, v in enumerate(seen, 1):
                out[f"{letter}{i}"] = (letter, v)
        return out

    def statements(self) -> dict[str, str]:
        """판단 대상 진술: 조합/개수형은 ㄱㄴㄷ…, 단일형은 보기 1~5, 괄호 넣기형은 빈칸에 후보 값을 넣은 문장."""
        if self.blanks:
            import re as _re

            out = {}
            for key, (letter, value) in self.blank_candidates().items():
                item = self.blank_items[letter]
                text = _re.sub(r"\(\s*" + letter + r"\s*\)", f"[{value}]", self.items[item])
                text = _re.sub(r"\(\s*([A-H])\s*\)", r"(빈칸 \1)", text)
                out[key] = f"({item} 진술, 빈칸 {letter} = {value}) {text}"
            return out
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
    missing: str | None = None   # 판단 프롬프트 v6: 더 찾아야 할 근거 (2차 검색 질의)
    stance: str | None = None    # 판단 프롬프트 v7: 인용 문장이 진술을 지지(supports)·반박(contradicts)·무관(none)

    @field_validator("quote", "missing", mode="before")
    @classmethod
    def _join_list(cls, v):
        return " ".join(str(x) for x in v) if isinstance(v, list) else v


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
    if q.form == "blank":
        right = q.blanks.get(q.answer, {})
        return {k: right.get(letter) == v for k, (letter, v) in q.blank_candidates().items()}
    return {}
