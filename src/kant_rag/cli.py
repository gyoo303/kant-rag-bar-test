"""명령줄 진입점.

  uv run kant-rag build-index
  uv run kant-rag ask "개봉 후 반품 가능한 조건은?" --mode hybrid_rerank
  uv run kant-rag search "개봉 반품" --mode hybrid
  uv run kant-rag eval eval/dev.json --modes vector hybrid hybrid_rerank
  uv run kant-rag grade results/<run_id>/grading.csv
  uv run kant-rag check-eval
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kant_rag.config import ROOT, get_settings


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kant-rag")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build-index", help="문서 목록 → 청크 → BM25/벡터 색인 재생성")
    sub.add_parser("chunks", help="청킹 결과만 출력 (모델 불필요)")

    for name in ("ask", "search"):
        sp = sub.add_parser(name)
        sp.add_argument("question")
        sp.add_argument("--mode", default="hybrid_rerank", choices=["vector", "hybrid", "hybrid_rerank"])

    ev = sub.add_parser("eval", help="평가셋 실행 (cache 는 설정에서 끈 상태로)")
    ev.add_argument("eval_path")
    ev.add_argument("--modes", nargs="+", default=["vector", "hybrid", "hybrid_rerank"])
    ev.add_argument("--label", default="")
    ev.add_argument("--rewrite", action="store_true", help="쿼리 리라이트 켜고 실행 (C+리라이트)")

    gr = sub.add_parser("grade", help="채점 완료 grading.csv 집계")
    gr.add_argument("grading_csv")

    sub.add_parser("check-eval", help="eval/dev.json, eval/test.json 스키마·구성 검사")

    args = p.parse_args(argv)
    settings = get_settings(args.config)

    if args.cmd == "build-index":
        from kant_rag.ingest.build_index import build_index

        print(json.dumps(build_index(settings), ensure_ascii=False, indent=2))

    elif args.cmd == "chunks":
        from kant_rag.ingest.build_index import build_chunks

        for c in build_chunks(settings):
            print(f"{c.chunk_id}\t{c.location()}\t{c.text[:60]!r}")

    elif args.cmd in ("ask", "search"):
        from kant_rag.retrieval.pipeline import RetrievalMode

        mode = RetrievalMode(args.mode)
        if args.cmd == "search":
            from kant_rag.retrieval.pipeline import Retriever

            stages = Retriever(settings).retrieve(args.question, mode)
            for name, rs in stages.items():
                print(f"--- {name}")
                for r in rs:
                    print(f"{r.rank:>2} {r.score:.4f} {r.chunk.chunk_id} {r.chunk.location()}")
        else:
            from kant_rag.agent import KnowledgeAgent

            rec = KnowledgeAgent(settings).ask(args.question, mode=mode)
            print(json.dumps(rec["answer"], ensure_ascii=False, indent=2))
            print("timing_ms:", rec["timing_ms"])

    elif args.cmd == "eval":
        from kant_rag.evaluation.runner import run_eval
        from kant_rag.retrieval.pipeline import RetrievalMode

        s = settings.model_copy(deep=True)
        if s.optimization.cache.enabled:
            raise SystemExit("품질 비교 실행에서는 캐시를 꺼야 합니다 (optimization.cache.enabled=false)")
        s.optimization.rewrite.enabled = args.rewrite
        out = run_eval(s, Path(args.eval_path), [RetrievalMode(m) for m in args.modes], args.label)
        print("saved:", out)

    elif args.cmd == "grade":
        from kant_rag.evaluation.runner import aggregate_grading

        print(json.dumps(aggregate_grading(Path(args.grading_csv)), ensure_ascii=False, indent=2))

    elif args.cmd == "check-eval":
        from kant_rag.evaluation.dataset import check_composition, load_evalset

        for name in ("dev", "test"):
            es = load_evalset(ROOT / "eval" / f"{name}.json")
            warns = check_composition(es)
            print(f"{name}: {len(es.items)}문항, version={es.version}, frozen={es.frozen}")
            for w in warns:
                print("  ⚠", w)


if __name__ == "__main__":
    main()
