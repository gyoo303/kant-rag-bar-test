"""시험지 가져오기 / 평가셋 분리."""

from __future__ import annotations

import csv
import re
import json
import random
from pathlib import Path

from pydantic import BaseModel, Field

from kant_rag.evaluation.dataset import EvalItem
from kant_rag.mcq.parse import parse_exam_text
from kant_rag.mcq.schemas import ExamQuestion


class Exam(BaseModel):
    exam: str  # 예: "2026 제15회 변호사시험 민사법 선택형"
    source: str
    items: list[ExamQuestion]


class BarEvalSet(BaseModel):
    """발제 구성: dev = 선택형 8 + 근거 없음 2 / test = 선택형 17(direct 10 + paraphrase 7) + 근거 없음 3."""

    version: str
    split: str
    frozen: bool = False
    frozen_at: str | None = None      # freeze-test 가 기록 (고정 시각)
    frozen_commit: str | None = None  # 고정 당시 코드 커밋
    items: list[ExamQuestion]
    no_answer: list[EvalItem] = Field(default_factory=list)


def parse_answer_cell(cell: str) -> tuple[int, list[int]]:
    """정답 칸 "4" → (4, []), 복수 정답 "4|5" → (4, [4, 5]) (첫 번호가 대표 정답)."""
    nums = [int(x) for x in re.split(r"[|/;]", str(cell)) if x.strip()]
    return nums[0], (nums if len(nums) > 1 else [])


def import_exam(text_path: Path, answers_csv: Path | None, exam: str, source: str, id_prefix: str) -> Exam:
    items = parse_exam_text(text_path.read_text(encoding="utf-8"), id_prefix=id_prefix, subject=None)
    if answers_csv:
        with answers_csv.open(encoding="utf-8-sig") as f:
            key = {int(r["number"]): parse_answer_cell(r["answer"]) for r in csv.DictReader(f)}
        from kant_rag.mcq.schemas import derive_statement_labels

        for q in items:
            q.answer, q.accepted = key.get(q.number, (None, []))
            if q.answer is not None:
                q.statement_labels = derive_statement_labels(q)  # 진술 단위 지표용 (apply-answers 와 동일)
    return Exam(exam=exam, source=source, items=items)


def split_exam(exam: Exam, seed: int = 2026, n_dev: int = 8, n_test: int = 17) -> dict[str, list[ExamQuestion]]:
    """고정 seed 로 과목 비례 층화 무작위 분리. 결과 파일을 커밋해 고정하고, 이후 재분리하지 않습니다."""
    rng = random.Random(seed)
    groups: dict[str, list[ExamQuestion]] = {}
    for q in sorted(exam.items, key=lambda q: q.number):
        groups.setdefault(q.subject or "-", []).append(q)
    for g in groups.values():
        rng.shuffle(g)
    total = len(exam.items)
    out: dict[str, list[ExamQuestion]] = {"dev": [], "test": [], "extra": []}
    # 과목별 할당량: 비율대로 내림 후 남는 자리는 큰 과목부터
    def quota(n: int) -> dict[str, int]:
        base = {k: n * len(g) // total for k, g in groups.items()}
        for k in sorted(groups, key=lambda k: -len(groups[k]))[: n - sum(base.values())]:
            base[k] += 1
        return base
    qd, qt = quota(n_dev), quota(n_test)
    for k, g in groups.items():
        out["dev"] += g[: qd[k]]
        out["test"] += g[qd[k]: qd[k] + qt[k]]
        out["extra"] += g[qd[k] + qt[k]:]
    for split, qs in out.items():
        for q in qs:
            q.split = split  # type: ignore[assignment]
        qs.sort(key=lambda q: q.number)
    return out


def load_bar_evalset(path: Path) -> BarEvalSet:
    """평가셋(eval/dev.json 등) 또는 시험 문항 파일(data/exam/2026_civil.json, *_extra.json) 모두 허용."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "exam" in data:  # 시험 문항 파일 → 근거 없음 문항 없이 선택형만
        from kant_rag.mcq.traps import auto_traps

        exam = Exam.model_validate(data)
        for q in exam.items:
            q.traps = q.traps or auto_traps(q)
        if path.stem.endswith("_extra"):
            split = "extra"
        elif path.stem.endswith("_tune"):
            split = "tune"
        elif path.stem.startswith("2026_civil"):
            split = "all"  # dev·test 를 포함한 본 시험 전체
        else:
            split = "external"  # 다른 시험지 (평가셋 분리와 무관)
        return BarEvalSet(version=f"exam:{path.name}", split=split, items=exam.items)
    return BarEvalSet.model_validate(data)


def check_bar_composition(es: BarEvalSet) -> list[str]:
    exp = {"dev": (8, 2), "test": (17, 3)}.get(es.split)
    warns = []
    if exp:
        if len(es.items) != exp[0]:
            warns.append(f"선택형 문항: 기대 {exp[0]}, 현재 {len(es.items)}")
        if len(es.no_answer) != exp[1]:
            warns.append(f"근거 없음 문항: 기대 {exp[1]}, 현재 {len(es.no_answer)}")
    missing = [q.id for q in es.items if q.answer is None]
    if missing:
        warns.append(f"정답 미기입: {missing}")
    if es.split == "test":
        n_direct = sum(q.type == "direct" for q in es.items)
        n_para = sum(q.type == "paraphrase" for q in es.items)
        if (n_direct, n_para) != (10, 7):
            warns.append(f"test 유형 구성(direct/paraphrase): 기대 10/7, 현재 {n_direct}/{n_para}")
    return warns
