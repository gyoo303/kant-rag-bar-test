"""AI 함정 유형 태그.

자동 태그(문장 형태로 판별 가능)는 여기서 붙이고, 법적 판단이 필요한 태그는 팀이 `traps` 에 직접 추가합니다.
정답률·Hit@5 를 태그별로 나눠 '어떤 함정을 RAG 가 막는가 / 못 막는가' 를 분석합니다.
"""

from __future__ import annotations

import re

from kant_rag.mcq.schemas import ExamQuestion

TRAP_DESCRIPTIONS = {
    # 자동
    "숫자·기간": "진술에 기간·기한·금액·비율 등 숫자 — 숫자만 살짝 바꾸는 함정",
    "부정 극성": "'옳지 않은 것' 을 고르는 발문 — 극성을 뒤집어 고르는 실수",
    "전 진술 판단": "조합형·○× 조합형 — 진술 하나만 틀려도 오답",
    "사례 적용": "발문에 구체적 사례(당사자·사실관계) — 법리를 사례에 적용하는 다단계 추론",
    "예외·단서": "'특별한 사정이 없는 한', '~하더라도', '~에 한하여' 등 예외·조건 표현",
    "복수 법령": "한 문항에 서로 다른 법령이 둘 이상 등장",
    # 수동 (팀 판단)
    "최신 판례": "2023~2025 선고 판례 법리 — 모델 학습 시점 이후일 수 있음",
    "판례 변경": "전원합의체 등으로 종전 판례가 변경된 법리",
    "유사 제도 혼동": "비슷한 제도·요건을 바꿔 끼운 진술 (예: 소멸시효↔제척기간, 대리↔대표)",
    "주체·객체 바꿔치기": "권리자/의무자, 원고/피고 등 주체를 바꾼 진술",
}
AUTO = ["숫자·기간", "부정 극성", "전 진술 판단", "사례 적용", "예외·단서", "복수 법령"]

NUM = re.compile(r"\d+\s*(년|개월|월|일|주|시간|%|퍼센트|배|분의|원|억|만)|[0-9]+/[0-9]+|\d+분의\s*\d+")
EXCEPT = re.compile(r"특별한 사정이 없는 한|하더라도|이더라도|에 한하여|에 한한다|에 불과|예외적으로|다만")
LAW = re.compile(r"｢([^｣]+)｣")


def auto_traps(q: ExamQuestion) -> list[str]:
    text = " ".join(q.statements().values())
    tags = []
    if NUM.search(text):
        tags.append("숫자·기간")
    if q.form in ("single", "combination") and q.polarity == "incorrect":
        tags.append("부정 극성")
    if q.form in ("combination", "ox", "count"):
        tags.append("전 진술 판단")
    if q.type == "paraphrase":
        tags.append("사례 적용")
    if EXCEPT.search(text):
        tags.append("예외·단서")
    if len({m for m in LAW.findall(q.stem + " " + text)}) >= 2:
        tags.append("복수 법령")
    return tags
