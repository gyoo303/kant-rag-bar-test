"""corpus 도메인 예외 (04-interfaces-api §1.6, ADR-015). 표준 라이브러리만 사용."""

from __future__ import annotations

# 가져오기 문제 사유 (03-db-schema §3 import_issues.reason)
MISSING_FIELD = "MISSING_FIELD"
BAD_DATE = "BAD_DATE"
JSON_ERROR = "JSON_ERROR"
EMPTY_CONTENT = "EMPTY_CONTENT"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
DUPLICATE_ARTICLE = "DUPLICATE_ARTICLE"


class InvalidSourceDocumentError(ValueError):
    """가져오기 한 건이 규칙에 맞지 않음. `reason`은 import_issues.reason 값."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class OutOfScopeError(InvalidSourceDocumentError):
    """범위 밖 문서(민사가 아닌 판례 등, ADR-015)."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(OUT_OF_SCOPE, detail)
