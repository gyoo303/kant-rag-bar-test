"""캐시 검증 실험 (선택 시 필수 15건): 질문 5개 × [미적중, 동일 질문 적중, 문서/색인 버전 변경 후 재요청]."""

from __future__ import annotations

import json
import time
from pathlib import Path

from kant_rag.agent import KnowledgeAgent
from kant_rag.config import Settings
from kant_rag.retrieval.pipeline import RetrievalMode, Retriever


def run_cache_experiment(settings: Settings, questions: list[tuple[str, str]], bumped_index_version: str) -> Path:
    s = settings.model_copy(deep=True)
    s.optimization.cache.enabled = True
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-cache"
    out = settings.resolve(settings.paths.results_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)

    retriever = Retriever(s)
    agent = KnowledgeAgent(s, retriever)
    agent.cache.invalidate()  # 실험 시작 전 캐시 초기화 (조건 명시)

    s2 = s.model_copy(deep=True)
    s2.versions.index = bumped_index_version  # 실제 실험에서는 색인을 재생성한 뒤 버전을 올립니다
    agent2 = KnowledgeAgent(s2, retriever)

    with (out / "cache_records.jsonl").open("w", encoding="utf-8") as f:
        for qid, q in questions:
            for phase, a in (("miss", agent), ("hit", agent), ("after_version_change", agent2)):
                rec = a.ask(q, mode=RetrievalMode.C, question_id=qid, run_id=run_id)
                rec["cache_phase"] = phase
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(qid, phase, rec.get("cache"), rec["timing_ms"]["total"], "ms")
    return out
