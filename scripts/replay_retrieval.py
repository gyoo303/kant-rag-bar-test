"""시험 풀이 실행(runs.jsonl)에 기록된 검색어를 그대로 다시 검색해 단계별 순위를 남긴다 (분석용).

풀이 때 지문 판단에 쓴 후보는 순위 없이 저장되므로, 같은 검색어로 벡터·BM25·결합·재정렬 순위를 재현한다.
쿼리 임베딩은 CacheBackedEmbeddings 캐시에 있어 OpenAI 호출 없이 돈다(캐시에 없으면 그 질의만 호출).
풀이 때와 같은 시점 필터를 쓰려면 RETRIEVAL_DATE_TO 를 같은 값으로 준다.

사용:
  RETRIEVAL_DATE_TO=20221231 uv run python scripts/replay_retrieval.py results/<batch>/C_statements
→ <run_dir>/retrieval_replay.json  {문항: {질의 이름: {query, mode, vector, bm25, fused, reranked}}}
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from civil_rag.retrieval.pipeline import Retriever

LIGHT = (":alone", ":issue", ":exception", ":plain")   # v3 에서 재정렬 없이(B) 검색한 보조 질의 (v1 재검토 :retry 는 C)


def main(run_dir: str, workers: int = 4, no_rerank: bool = False) -> Path:
    """no_rerank=True 면 재정렬(CPU 질의당 약 2초)을 건너뛰고 벡터·BM25·결합 순위만 재현한다."""
    run = Path(run_dir)
    runs = [json.loads(line) for line in (run / "runs.jsonl").open(encoding="utf-8")]
    r = Retriever()
    _ = r.bm25, r._bm25_matrix, r.vector_store
    jobs = []
    for rec in runs:
        for name, q in (rec.get("queries") or {}).items():
            if not isinstance(q, dict) or "query" not in q:
                continue
            mode = "B" if (no_rerank or name.endswith(LIGHT)) else "C"
            jobs.append((rec["no"], name, q["query"], mode))

    def one(job):
        no, name, query, mode = job
        res = r.retrieve(query, mode=mode)
        st = res.stages
        return no, name, {"query": query, "mode": mode, "vector": st.get("vector", []), "bm25": st.get("bm25", []),
                          "fused": st.get("fused", []), "reranked": st.get("reranked", [])}

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (no, name, data) in enumerate(ex.map(one, jobs), 1):
            out.setdefault(str(no), {})[name] = data
            if i % 50 == 0:
                print(f"{i}/{len(jobs)}", flush=True)
    path = run / "retrieval_replay.json"
    path.write_text(json.dumps({"date_to": r.date_to, "items": out}, ensure_ascii=False), encoding="utf-8")
    print(f"{len(jobs)}개 질의 재현 → {path}")
    return path


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4, "--no-rerank" in sys.argv)
