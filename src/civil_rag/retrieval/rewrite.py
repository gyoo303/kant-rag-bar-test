"""쿼리 리라이트 (교안 4-4 Rewrite, 노션 STEP 5 선택 최적화).

- 원질문과 변환 질의를 모두 기록한다.
- 정답·허용 근거는 리라이터에 절대 넣지 않는다 (질문 원문만 입력).
- 오류·빈 결과·지나치게 긴 결과면 원질문으로 fallback 한다.
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from civil_rag.models import chat_model

REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "당신은 한국 민사법 판례 검색 도우미입니다.\n"
     "사용자의 질문이나 시험 지문을 판례·법조문 검색에 적합한 검색 질의 한 줄로 바꾸세요.\n"
     "규칙:\n"
     "1. 질문의 법적 쟁점(법리), 관련 법률 용어, 관련 조문(예: 민법 제750조)을 중심으로 쓴다.\n"
     "2. 사례 속 인물·금액·날짜 같은 구체적 사실은 법적으로 의미 있는 요소만 남긴다.\n"
     "3. 옳다/그르다 같은 결론이나 정답을 추측해 넣지 않는다.\n"
     "4. 원래 질문의 의도를 바꾸지 않는다.\n"
     "5. 설명 없이 검색 질의만 출력한다."),
    ("human", "{question}"),
])

MAX_REWRITE_LEN = 300


def rewrite_query(question: str) -> tuple[str, str]:
    """반환: (검색에 쓸 질의, 상태 'ok' | 'fallback:<사유>')."""
    try:
        chain = REWRITE_PROMPT | chat_model() | StrOutputParser()
        out = (chain.invoke({"question": question}) or "").strip().strip('"').strip()
    except Exception as e:  # noqa: BLE001 — 어떤 오류든 원질문으로 대체하고 사유를 남긴다
        return question, f"fallback:error:{type(e).__name__}"
    if not out:
        return question, "fallback:empty"
    if len(out) > MAX_REWRITE_LEN:
        return question, "fallback:too_long"
    return out, "ok"
