"""명령행 진입점:  uv run civil-rag <명령> ...

  ingest     원문 → 청크(data/index/chunks.jsonl)            (API 비용 없음)
  index      청크 → 벡터 저장소 (임베딩, OpenAI 비용 발생)
  search     검색만 실행해 후보 확인 — 평가셋 근거 매핑용 (bm25 모드는 비용 없음)
  ask        질문 1개 답변 (구성 선택)
  check-eval 평가셋 구성·스키마 점검
  eval       고정 평가 실행 → results/
  exam       시험지(5지선다) 풀이·채점 → results/
  ragas      RAGAS 보조 지표
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _ingest(a):
    from civil_rag.ingest.build import build_chunks

    build_chunks(
        limit=a.limit,
        court=a.court,
        keywords=[k for k in (a.keywords or "").split(",") if k.strip()],
        ids_file=Path(a.ids_file) if a.ids_file else None,
        laws=a.laws,
    )


def _index(a):
    from civil_rag.ingest.build import build_vector_index

    build_vector_index(a.backend)


def _search(a):
    from civil_rag.retrieval.pipeline import Retriever

    r = Retriever(backend=a.backend)
    if a.mode == "bm25":
        hits = r.bm25_search(a.query, a.k)
        for rank, (cid, score) in enumerate(hits, 1):
            c = r._candidate(cid)
            print(f"{rank:>2}. {score:7.2f}  {cid}\n    {c.cite_label()}\n    {c.text.split(chr(10), 1)[-1][:160]}")
        return
    res = r.retrieve(a.query, mode=a.mode, rewrite=a.rewrite)
    if res.rewritten_query:
        print(f"변환 질의: {res.rewritten_query}")
    for rank, c in enumerate(res.final, 1):
        scores = ", ".join(f"{k}={v:.3f}" for k, v in (
            ("bm25", c.bm25_score), ("vec", c.vector_score), ("rrf", c.fused_score), ("rerank", c.rerank_score))
            if v is not None)
        print(f"{rank:>2}. {c.chunk_id}  ({scores})\n    {c.cite_label()}\n    {c.text.split(chr(10), 1)[-1][:160]}")
    print(f"timings: { {k: round(v, 2) for k, v in res.timings.items()} }")


def _ask(a):
    from civil_rag.agent import LegalRAG

    res = LegalRAG().ask(a.question, a.config)
    if a.json:
        print(json.dumps(res.to_record(), ensure_ascii=False, indent=2))
        return
    ans = res.answer
    print(f"[{res.run_config}] 상태={ans.status} 판단={ans.verdict} ({res.total_seconds:.1f}s)")
    if res.retrieval and res.retrieval.rewritten_query:
        print(f"변환 질의: {res.retrieval.rewritten_query}")
    print("\n" + (ans.answer or ans.error or ""))
    if res.retrieval:
        print("\n근거:")
        for n, c in enumerate(res.retrieval.final, 1):
            mark = "★" if n in ans.valid_citations else " "
            print(f" {mark}[문서 {n}] {c.cite_label()}  ({c.chunk_id})")
        if not ans.citation_valid:
            print(f" ! 검색 결과에 없는 인용 번호: {sorted(set(ans.citations) - set(ans.valid_citations))}")


def _check_eval(a):
    from civil_rag.evaluation.dataset import load_eval, validate

    for split in a.splits:
        version, items = load_eval(split)
        probs = validate(split)
        print(f"[{split}] version={version} 문항={len(items)} → " + ("통과" if not probs else f"문제 {len(probs)}건"))
        for p in probs:
            print("  -", p)


def _eval(a):
    from civil_rag.evaluation.runner import run_eval

    run_eval(a.split, a.configs, limit=a.limit, tag=a.tag, strict=a.strict)


def _exam(a):
    from civil_rag.exam.runner import run_exam

    run_exam(Path(a.exam_file), a.configs, strategy=a.strategy, limit=a.limit, numbers=a.numbers, tag=a.tag)


def _ragas(a):
    from civil_rag.evaluation.ragas_eval import run_ragas

    run_ragas(Path(a.run_dir), a.split)


def main(argv: list[str] | None = None) -> None:
    from civil_rag.agent import RUN_CONFIGS

    p = argparse.ArgumentParser(prog="civil-rag", description="민사법 판례 RAG")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="원문 → 청크")
    s.add_argument("--limit", type=int, default=0, help="판례 최대 건수 (0=전부)")
    s.add_argument("--court", default=None, help='법원명 필터, 예: "대법원"')
    s.add_argument("--keywords", default=None, help='사건명·판시사항·판결요지·참조조문에 포함될 단어(쉼표 구분), 예: "임대차,소멸시효"')
    s.add_argument("--ids-file", default=None, help="판례일련번호 목록 파일(줄마다 1개)")
    s.add_argument("--laws", nargs="*", default=None, help="포함할 법령명 (생략 시 수집된 법령 전부)")
    s.set_defaults(func=_ingest)

    s = sub.add_parser("index", help="청크 → 벡터 저장소 (임베딩)")
    s.add_argument("--backend", choices=["pgvector", "memory"], default=None)
    s.set_defaults(func=_index)

    s = sub.add_parser("search", help="검색 결과만 보기 (근거 매핑용)")
    s.add_argument("query")
    s.add_argument("--mode", choices=["bm25", "A", "B", "C"], default="bm25")
    s.add_argument("--rewrite", action="store_true")
    s.add_argument("--k", type=int, default=10, help="bm25 모드 결과 수")
    s.add_argument("--backend", choices=["pgvector", "memory"], default=None)
    s.set_defaults(func=_search)

    s = sub.add_parser("ask", help="질문 1개")
    s.add_argument("question")
    s.add_argument("--config", choices=list(RUN_CONFIGS), default="C")
    s.add_argument("--json", action="store_true", help="원본 기록 JSON 출력")
    s.set_defaults(func=_ask)

    s = sub.add_parser("check-eval", help="평가셋 점검")
    s.add_argument("splits", nargs="*", default=["dev", "test"])
    s.set_defaults(func=_check_eval)

    s = sub.add_parser("eval", help="고정 평가 실행")
    s.add_argument("--split", choices=["dev", "test"], default="dev")
    s.add_argument("--configs", nargs="+", choices=list(RUN_CONFIGS), default=["A", "B", "C"])
    s.add_argument("--limit", type=int, default=0, help="앞에서 N문항만 (빠른 점검용, 본 평가에선 쓰지 않음)")
    s.add_argument("--tag", default="", help="결과 폴더 이름 꼬리표")
    s.add_argument("--strict", action="store_true", help="평가셋 점검 실패 시 중단 (최종 평가 때 사용)")
    s.set_defaults(func=_eval)

    s = sub.add_parser("exam", help="시험지(5지선다) 풀이·채점")
    s.add_argument("exam_file", help="exams/<시험>.json")
    s.add_argument("--configs", nargs="+", choices=list(RUN_CONFIGS), default=["C"])
    s.add_argument("--strategy", choices=["whole", "per_choice"], default="whole")
    s.add_argument("--numbers", nargs="*", type=int, default=None, help="특정 문항 번호만")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--tag", default="")
    s.set_defaults(func=_exam)

    s = sub.add_parser("ragas", help="RAGAS 보조 지표")
    s.add_argument("run_dir", help="results/<batch>/<구성> 폴더")
    s.add_argument("--split", choices=["dev", "test"], default="dev")
    s.set_defaults(func=_ragas)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
