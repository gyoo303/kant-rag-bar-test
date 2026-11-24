"""answering 계약 (SEQ-03). 구현은 `answering.infrastructure`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from lawqa.answering.domain.models import ModelAnswer
from lawqa.retrieval.domain.models import Candidate, ExamItem


class AnswerGenerator(Protocol):
    """문항과 근거 후보로 모델 답을 만든다.

    실패하면 `ModelCallError`·`ModelTimeoutError`·`ModelOutputFormatError`.
    """

    def generate(self, item: ExamItem, context: Sequence[Candidate]) -> ModelAnswer: ...
