"""문항 → 검색 질의 5개 (ADR-011 규칙 기반 분해, 모델 호출 없음).

두 가지 문항 구조를 나눠 다룬다(CR-020).

- **일반형**: 판단할 법적 명제가 보기 ①~⑤ 안에 있다 → 보기마다 질의 하나(기존 방식).
- **조합형**: 명제 ㄱ·ㄴ·ㄷ·ㄹ이 **지문 안에** 있고 보기는 "ㄱ, ㄴ" 같은 조합 기호뿐이다.
  보기로 질의를 만들면 5개가 사실상 같아져 후보가 줄고 일부 명제는 검색조차 되지 않는다
  (2026 선택형 실패 분석: 틀린 10문항이 전부 조합형). 그래서 **명제마다 질의 하나**를 만든다.

어느 쪽이든 질의 5개(슬롯 1~5)를 돌려준다. `RetrievalResult`가 1~5를 요구하기 때문이다.
명제가 5개보다 적으면 남는 슬롯은 지문의 물음 문장으로 채운다(주제 전반을 훑는 질의).
"""

from __future__ import annotations

import re

from lawqa.retrieval.domain.models import OPTION_COUNT, ExamItem, OptionQuery

STEM_PREFIX_CHARS = 300  # 일반형 질의 = 지문 앞 300자 + 보기 원문
PROPOSITION_MIN = 2  # 명제가 2개 이상이어야 조합형으로 본다
_PROPOSITION = re.compile(r"^([ㄱ-ㅎ])\.[ \t]*", re.MULTILINE)


def split_propositions(stem: str) -> tuple[str, list[tuple[str, str]]]:
    """지문을 (물음 문장, [(표시, 명제 본문)])로 나눈다. 조합형이 아니면 명제 목록이 빈다."""
    marks = list(_PROPOSITION.finditer(stem))
    if len(marks) < PROPOSITION_MIN:
        return stem.strip(), []
    head = stem[: marks[0].start()].strip()
    items: list[tuple[str, str]] = []
    for pos, mark in enumerate(marks):
        end = marks[pos + 1].start() if pos + 1 < len(marks) else len(stem)
        body = stem[mark.end() : end].strip()
        if body:
            items.append((mark.group(1), body))
    return head, items


class QueryDecomposer:
    def decompose(self, item: ExamItem) -> list[OptionQuery]:
        head, propositions = split_propositions(item.stem)
        if propositions:
            return self._by_proposition(head, propositions)
        return self._by_option(item)

    def _by_option(self, item: ExamItem) -> list[OptionQuery]:
        """일반형: 지문 앞부분 + 보기 원문."""
        stem = item.stem.strip()[:STEM_PREFIX_CHARS]
        return [
            OptionQuery(option_no=no, original=f"{stem}\n{option.strip()}")
            for no, option in enumerate(item.options, start=1)
        ]

    def _by_proposition(self, head: str, propositions: list[tuple[str, str]]) -> list[OptionQuery]:
        """조합형: 명제마다 질의 하나. 남는 슬롯은 물음 문장만(주제 전반)."""
        topic = head[:STEM_PREFIX_CHARS].strip() or propositions[0][1][:STEM_PREFIX_CHARS]
        queries: list[OptionQuery] = []
        for slot in range(1, OPTION_COUNT + 1):
            if slot <= len(propositions):
                mark, body = propositions[slot - 1]
                text = f"{topic}\n{mark}. {body}"[: STEM_PREFIX_CHARS * 3]
            else:
                text = topic
            queries.append(OptionQuery(option_no=slot, original=text))
        return queries


def followup_queries(item: ExamItem, insufficient_options: set[int]) -> list[OptionQuery]:
    """근거가 모자란 보기에 걸린 **명제만** 다시 찾을 질의 (CR-019).

    1차 답변에서 모델이 `insufficient`로 표시한 보기를 받아, 그 보기가 가리키는 명제의 질의를
    돌려준다. 조합형이면 보기 "ㄱ, ㄴ"이 가리키는 ㄱ·ㄴ 명제를, 일반형이면 그 보기 자체를 쓴다.
    다시 찾을 것이 없으면 빈 목록(2차 검색을 건너뛴다).
    """
    if not insufficient_options:
        return []
    head, propositions = split_propositions(item.stem)
    decomposer = QueryDecomposer()
    if not propositions:
        return [q for q in decomposer.decompose(item) if q.option_no in insufficient_options]

    wanted: set[str] = set()
    for no in insufficient_options:
        if 1 <= no <= len(item.options):
            wanted |= {
                m
                for m, _ in propositions
                if re.search(rf"(?:^|[^가-힣]){m}(?![가-힣])", item.options[no - 1])
            }
    if not wanted:
        return []
    picked = [(m, body) for m, body in propositions if m in wanted]
    full = decomposer._by_proposition(head, picked)
    return full[: len(picked)]
