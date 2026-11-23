"""명령줄 진입점.

  uv run kant-rag build-index
  uv run kant-rag ask "개봉 후 반품 가능한 조건은?" --mode hybrid_rerank
  uv run kant-rag search "개봉 반품" --mode hybrid
  uv run kant-rag grade results/<run_id>/grading.csv
  uv run kant-rag check-eval

  # 변호사시험 선택형
  uv run kant-rag import-exam data/exam/2026_civil.txt --answers data/exam/2026_civil_answers.csv
  uv run kant-rag split-exam data/exam/2026_civil.json
  uv run kant-rag solve data/exam/2026_civil.json 12 --mode hybrid_rerank
  uv run kant-rag eval eval/dev.json --label dev
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

    gr = sub.add_parser("grade", help="채점 완료 grading.csv 집계")
    gr.add_argument("grading_csv")

    sub.add_parser("check-eval", help="eval/*.json 스키마·구성 검사")

    ie = sub.add_parser("import-exam", help="시험지 텍스트 + 정답 CSV → 문항 JSON")
    ie.add_argument("text_path")
    ie.add_argument("--answers", default=None)
    ie.add_argument("--exam", default="2026 제15회 변호사시험 민사법 선택형")
    ie.add_argument("--source", default="법무부 공개 문제")
    ie.add_argument("--prefix", default="BAR2026-CIV")
    ie.add_argument("--out", default=None)
    ie.add_argument("--subjects", default="1-35:민법,36-51:민사소송법,52-70:상법",
                    help="문항 번호 구간별 과목 (시험지 배치 기준)")

    se = sub.add_parser("split-exam", help="문항 JSON → eval/dev.json(8) · eval/test.json(17) · *_extra.json")
    se.add_argument("exam_json")
    se.add_argument("--seed", type=int, default=2026)
    se.add_argument("--force", action="store_true", help="이미 있는 평가셋 덮어쓰기")

    aa = sub.add_parser("apply-answers", help="정답 CSV(number,answer)를 문항 JSON·extra·eval/dev·test 에 반영 (분리 유지)")
    aa.add_argument("answers_csv")
    aa.add_argument("--exam-json", default="data/exam/2026_civil.json")

    sv = sub.add_parser("solve", help="시험 문항 1개 풀이")
    sv.add_argument("exam_json")
    sv.add_argument("number", type=int)
    sv.add_argument("--mode", default="hybrid_rerank", choices=["vector", "hybrid", "hybrid_rerank"])
    sv.add_argument("--show-answer", action="store_true")

    eb = sub.add_parser("eval", help="평가셋 실행: 선택형 + 근거 없음 문항 × 구성 A/B/C (캐시는 꺼진 상태)")
    eb.add_argument("eval_path")
    eb.add_argument("--modes", nargs="+", default=["vector", "hybrid", "hybrid_rerank"])
    eb.add_argument("--label", default="")
    eb.add_argument("--rewrite", action="store_true", help="근거 없음 문항 경로에 쿼리 리라이트 적용")

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

    elif args.cmd == "grade":
        from kant_rag.mcq.evaluate import aggregate_grading

        print(json.dumps(aggregate_grading(Path(args.grading_csv)), ensure_ascii=False, indent=2))

    elif args.cmd == "check-eval":
        from kant_rag.mcq.io import check_bar_composition, load_bar_evalset

        for name in ("dev", "test"):
            path = ROOT / "eval" / f"{name}.json"
            bs = load_bar_evalset(path)
            print(f"{name}.json: 선택형 {len(bs.items)} + 근거 없음 {len(bs.no_answer)}, "
                  f"version={bs.version}, frozen={bs.frozen}")
            for w in check_bar_composition(bs):
                print("  ⚠", w)

    elif args.cmd == "import-exam":
        from kant_rag.mcq.io import import_exam

        src = Path(args.text_path)
        exam = import_exam(src, Path(args.answers) if args.answers else None, args.exam, args.source, args.prefix)
        for part in filter(None, args.subjects.split(",")):
            rng, name = part.split(":")
            lo, hi = (int(x) for x in rng.split("-"))
            for q in exam.items:
                if lo <= q.number <= hi:
                    q.subject = name
        out = Path(args.out) if args.out else src.with_suffix(".json")
        out.write_text(exam.model_dump_json(indent=2), encoding="utf-8")
        forms: dict[str, int] = {}
        subjects: dict[str, int] = {}
        for q in exam.items:
            subjects[q.subject or "-"] = subjects.get(q.subject or "-", 0) + 1
        for q in exam.items:
            forms[q.form] = forms.get(q.form, 0) + 1
        print(f"{len(exam.items)}문항 → {out}  형식={forms}  과목={subjects}  "
              f"정답 미기입={[q.number for q in exam.items if q.answer is None]}")
        print("⚠ 파싱 결과를 원본과 대조해 발문·보기·subject 를 수정하세요.")

    elif args.cmd == "split-exam":
        from kant_rag.mcq.io import BarEvalSet, Exam, split_exam

        exam = Exam.model_validate_json(Path(args.exam_json).read_text(encoding="utf-8"))
        parts = split_exam(exam, seed=args.seed)
        for split in ("dev", "test"):
            path = ROOT / "eval" / f"{split}.json"
            no_answer = []
            if path.exists():
                old = BarEvalSet.model_validate_json(path.read_text(encoding="utf-8"))
                if (old.items or old.frozen) and not args.force:
                    raise SystemExit(f"{path} 에 이미 문항이 있습니다 (고정된 평가셋 보호). 덮어쓰려면 --force")
                no_answer = old.no_answer  # 직접 작성한 근거 없음 문항은 유지
            es = BarEvalSet(version=settings.versions.eval, split=split, items=parts[split], no_answer=no_answer)
            path.write_text(es.model_dump_json(indent=2), encoding="utf-8")
            print(f"{split}: {[q.number for q in parts[split]]} → {path}")
        extra = Path(args.exam_json).with_name(Path(args.exam_json).stem + "_extra.json")
        extra.write_text(Exam(exam=exam.exam, source=exam.source, items=parts["extra"]).model_dump_json(indent=2),
                         encoding="utf-8")
        print(f"extra: {len(parts['extra'])}문항 → {extra} (본 평가와 분리)")
        print("다음: 각 문항 type(direct/paraphrase)·evidence 기입, no_answer 문항 작성, test 는 frozen=true")

    elif args.cmd == "apply-answers":
        import csv as _csv

        from kant_rag.mcq.io import BarEvalSet, Exam

        with open(args.answers_csv, encoding="utf-8-sig") as f:
            key = {int(r["number"]): int(r["answer"]) for r in _csv.DictReader(f)}
        exam_path = ROOT / args.exam_json
        targets = [(exam_path, Exam), (exam_path.with_name(exam_path.stem + "_extra.json"), Exam),
                   (ROOT / "eval" / "dev.json", BarEvalSet), (ROOT / "eval" / "test.json", BarEvalSet)]
        for path, model in targets:
            if not path.exists():
                continue
            obj = model.model_validate_json(path.read_text(encoding="utf-8"))
            if getattr(obj, "frozen", False):
                print(f"skip (frozen): {path}")
                continue
            n = 0
            for q in obj.items:
                if q.number in key and q.answer != key[q.number]:
                    q.answer = key[q.number]
                    n += 1
            path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
            missing = [q.number for q in obj.items if q.answer is None]
            print(f"{path.relative_to(ROOT)}: {n}개 반영, 미기입 {missing}")

    elif args.cmd == "solve":
        from kant_rag.mcq.io import Exam
        from kant_rag.mcq.solver import MCQSolver
        from kant_rag.retrieval.pipeline import RetrievalMode

        exam = Exam.model_validate_json(Path(args.exam_json).read_text(encoding="utf-8"))
        q = next(x for x in exam.items if x.number == args.number)
        rec = MCQSolver(settings).solve(q, RetrievalMode(args.mode))
        print(f"[문 {q.number}] form={q.form} polarity={q.polarity} status={rec['status']}")
        for k, j in (rec.get("judgments") or {}).items():
            print(f"  {k}: {j['verdict']} ({j['confidence']:.2f}) {j['reason'][:80]} {j['cited_chunk_ids']}")
        print("예측:", rec.get("predicted"), "| 보기 점수:", rec.get("option_scores"))
        if args.show_answer:
            print("정답:", q.answer)
        print("timing_ms:", rec["timing_ms"])

    elif args.cmd == "eval":
        from kant_rag.mcq.evaluate import run_bar_eval
        from kant_rag.retrieval.pipeline import RetrievalMode

        s = settings.model_copy(deep=True)
        if s.optimization.cache.enabled:
            raise SystemExit("품질 비교 실행에서는 캐시를 꺼야 합니다 (optimization.cache.enabled=false)")
        s.optimization.rewrite.enabled = args.rewrite
        print("saved:", run_bar_eval(s, Path(args.eval_path), [RetrievalMode(m) for m in args.modes], args.label))


if __name__ == "__main__":
    main()
