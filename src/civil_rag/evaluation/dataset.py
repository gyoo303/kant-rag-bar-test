"""평가셋 로딩·검증 (스키마: eval/README.md)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from civil_rag import config

TYPES = ("direct", "paraphrase", "no_evidence")

# 노션 STEP 2 구성
EXPECTED = {
    "dev": {"total": 10, "no_evidence": 2},
    "test": {"total": 20, "direct": 10, "paraphrase": 7, "no_evidence": 3},
}


def eval_path(split: str) -> Path:
    return config.EVAL_DIR / f"{split}.json"


def load_eval(split: str) -> tuple[str, list[dict]]:
    data = json.loads(eval_path(split).read_text(encoding="utf-8"))
    return data.get("version", f"{split}-unversioned"), data.get("items", [])


def is_answerable(item: dict) -> bool:
    return item.get("type") != "no_evidence"


def validate(split: str) -> list[str]:
    """노션 요구 구성과 스키마를 점검. 문제 목록을 돌려준다 (빈 목록이면 통과)."""
    problems: list[str] = []
    version, items = load_eval(split)
    if "draft" in version:
        problems.append(f"version '{version}' — 최종 평가 전 버전을 고정하세요 (예: {split}-v1)")
    ids = [it.get("id") for it in items]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        problems.append(f"중복 id: {dup}")
    counts = Counter(it.get("type") for it in items)
    exp = EXPECTED.get(split, {})
    if exp:
        if len(items) != exp["total"]:
            problems.append(f"문항 수 {len(items)} (기대 {exp['total']})")
        for t in TYPES:
            if t in exp and counts.get(t, 0) != exp[t]:
                problems.append(f"type={t} {counts.get(t, 0)}개 (기대 {exp[t]})")
    for it in items:
        iid = it.get("id", "?")
        if it.get("type") not in TYPES:
            problems.append(f"{iid}: type 은 {TYPES} 중 하나")
        if not it.get("question"):
            problems.append(f"{iid}: question 비어 있음")
        if is_answerable(it):
            if not it.get("allowed_evidence"):
                problems.append(f"{iid}: 답변 가능 문항인데 allowed_evidence 비어 있음")
            if not it.get("expected_answer"):
                problems.append(f"{iid}: expected_answer 비어 있음")
        else:
            if it.get("allowed_evidence"):
                problems.append(f"{iid}: 근거 없음 문항은 allowed_evidence 를 비워야 함")
            if not it.get("no_evidence_reason"):
                problems.append(f"{iid}: 근거 없음 판정 이유(no_evidence_reason) 없음")
    return problems
