"""문항 → 보기별 질의 5개 (ADR-011 규칙 기반 분해, 모델 호출 없음)."""

from __future__ import annotations

from lawqa.retrieval.domain.models import ExamItem, OptionQuery

STEM_PREFIX_CHARS = 300  # 질의 = 지문 앞 300자 + 보기 원문


class QueryDecomposer:
    def decompose(self, item: ExamItem) -> list[OptionQuery]:
        stem = item.stem.strip()[:STEM_PREFIX_CHARS]
        return [
            OptionQuery(option_no=no, original=f"{stem}\n{option.strip()}")
            for no, option in enumerate(item.options, start=1)
        ]
