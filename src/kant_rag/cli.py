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
import re
import sys
from pathlib import Path

from kant_rag.config import ROOT, get_settings


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kant-rag")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("api-check", help="law.go.kr API 연결·응답 구조 점검 (법령 1건, 판례 1건)")
    fl = sub.add_parser("fetch-laws", help="문서 목록의 법령(doc_type=statute)을 law.go.kr 에서 시험일 기준 버전으로 수집")
    fl.add_argument("--only", nargs="*", help="법령명 일부만 (기본: 목록 전체)")
    sub.add_parser("build-topics", help="수집한 법령 구조 → 판례 검색 주제어 (data/cases/topics.txt)")
    fc = sub.add_parser("fetch-cases", help="주제어별 대법원 판례 판결요지 수집 → data/raw/cases/cases.jsonl (재시작 가능)")
    fc.add_argument("--limit-topics", type=int, default=None, help="앞에서 N개 주제어만 (시험 실행용)")

    ic = sub.add_parser("import-cases", help="외부 판례 파일(폴더/.json/.jsonl) → data/raw/cases/cases_<연도>.jsonl (민사·가사, 시험일 이전, 판결요지만)")
    ic.add_argument("inputs", nargs="+")
    ic.add_argument("--source", default="팀 수집분")
    ic.add_argument("--dry-run", action="store_true", help="저장하지 않고 통계만")

    fd = sub.add_parser("find", help="근거 기입용 원문 검색: 모든 키워드를 포함한 청크 전부 (순위·검색기와 무관)")
    fd.add_argument("keywords", nargs="+", help="모두 포함(AND). 예: 성명 모용 표현대리")
    fd.add_argument("--limit", type=int, default=30)

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

    sub.add_parser("tag-traps", help="eval/dev·test 문항의 자동 함정 태그 재계산 (팀이 붙인 수동 태그는 유지)")
    aa = sub.add_parser("apply-answers", help="정답 CSV(number,answer)를 문항 JSON·extra·eval/dev·test 에 반영 (분리 유지)")
    aa.add_argument("answers_csv")
    aa.add_argument("--exam-json", default="data/exam/2026_civil.json")

    sv = sub.add_parser("solve", help="시험 문항 1개 풀이")
    sv.add_argument("exam_json")
    sv.add_argument("number", type=int)
    sv.add_argument("--mode", default="hybrid_rerank", choices=["vector", "hybrid", "hybrid_rerank", "closed_book"])
    sv.add_argument("--show-answer", action="store_true")
    sv.add_argument("--preset", default=None, help="개선안 단계: v2 | a1 | a2 | a34 | b | c(=v3)")
    sv.add_argument("--set", dest="sets", action="append", default=[], help="설정 덮어쓰기 key=value")

    st_ = sub.add_parser("solve-text", help="붙여넣은 시험지 텍스트를 변환 없이 바로 풀이 (문항 여러 개 가능)")
    st_.add_argument("text_path", help="시험지 텍스트 파일 (- 이면 표준입력)")
    st_.add_argument("--preset", default="v3", help="개선안 단계: v2 | a1 | a2 | a34 | b | c(=v3), 기본 v3")
    st_.add_argument("--mode", default="hybrid_rerank", choices=["vector", "hybrid", "hybrid_rerank", "closed_book"])
    st_.add_argument("--answers", default=None, help="정답(선택): '3,5,5,…' 또는 number,answer CSV 파일")
    st_.add_argument("--label", default="text")
    st_.add_argument("--set", dest="sets", action="append", default=[], help="설정 덮어쓰기 key=value")

    pg = sub.add_parser("progress", help="진행 중인 평가 실행의 문항별 예측/정답 표 (--watch 초 간격 새로고침)")
    pg.add_argument("label", help="결과 폴더 이름 끝부분, 예) bar13-v3")
    pg.add_argument("--watch", type=int, default=0, help="N초마다 다시 확인 (실행이 끝나면 멈춤, Ctrl+C 로 종료)")
    pg.add_argument("--total", type=int, default=None, help="전체 문항 수 (진행률 표시용)")

    eb = sub.add_parser("eval", help="평가셋 실행: 선택형 + 근거 없음 문항 × 구성 A/B/C (캐시는 꺼진 상태)")
    eb.add_argument("eval_path")
    eb.add_argument("--modes", nargs="+", default=["vector", "hybrid", "hybrid_rerank"],
                    choices=["vector", "hybrid", "hybrid_rerank", "closed_book"],
                    help="closed_book = 검색 없는 기준선 (선택형만, 본 60건과 별도 보고)")
    eb.add_argument("--label", default="")
    eb.add_argument("--rewrite", action="store_true", help="쿼리 리라이트 적용 (선택형 진술별 질의 + 근거 없음 문항)")
    eb.add_argument("--preset", default=None, help="개선안 단계: v2 | a1 | a2 | a34 | b | c(=v3) — mcq/presets.py")
    eb.add_argument("--set", dest="sets", action="append", default=[], help="설정 덮어쓰기 key=value (여러 번)")

    args = p.parse_args(argv)
    settings = get_settings(args.config)

    if args.cmd == "api-check":
        from kant_rag.ingest.lawapi import LawAPI

        api = LawAPI()

        def probe(label: str, endpoint: str, **params) -> None:
            try:
                body = api.raw(endpoint, **params)
            except Exception as e:
                print(f"[{label}] 오류 {type(e).__name__}: {e}")
                return
            try:
                data = json.loads(body)
            except ValueError:
                print(f"[{label}] JSON 아님: {body[:150]!r}")
                return
            top = list(data)[:3] if isinstance(data, dict) else type(data).__name__
            inner = data.get(top[0]) if isinstance(data, dict) and top else None
            keys = list(inner)[:12] if isinstance(inner, dict) else None
            cnt = inner.get("totalCnt") if isinstance(inner, dict) else None
            print(f"[{label}] top={top} totalCnt={cnt} keys={keys}")
            for k in ("law", "prec"):
                items = inner.get(k) if isinstance(inner, dict) else None
                if items:
                    first = items[0] if isinstance(items, list) else items
                    print(f"    {k}[0] = {json.dumps(first, ensure_ascii=False)[:300]}")

        c = settings.corpus
        print("=== 법령: 시험일 기준 버전 선택 ===")
        versions = api.law_versions("민법")
        print(f"민법 버전 {len(versions)}개, 최근 시행일자: {sorted({str(v.get('시행일자')) for v in versions})[-4:]}")
        info = api.find_law("민법", c.law_date)
        print(f"선택: 시행 {info.get('시행일자')} / 공포 {info.get('공포일자')} / MST {info.get('법령일련번호')} "
              f"/ {info.get('현행연혁코드')}")
        text = api.law_text(info["법령일련번호"], str(info.get("시행일자", "")))
        print(f"본문 {len(text.splitlines())}행, 예) {[l for l in text.splitlines() if l.startswith('제750조')][:1]}")
        print("=== 판례: 본문검색 + 기간·법원 필터 ===")
        hits = api.search_precs("표현대리", c.case_date_from, c.case_date_to, want=3)
        for h in hits[:3]:
            print(f"  {h.get('법원명')} {h.get('선고일자')} {h.get('사건번호')} (ID {h.get('판례일련번호')})")
        if hits:
            d = api.prec(str(hits[0].get("판례일련번호")))
            print("상세 필드:", sorted(d))
            print("판결요지:", str(d.get("판결요지", ""))[:150])

    elif args.cmd == "fetch-laws":
        import csv as _csv
        import time as _time

        from kant_rag.ingest.lawapi import LawAPI
        from kant_rag.ingest.loader import read_manifest

        api = LawAPI()
        manifest = settings.resolve(settings.paths.manifest)
        docs = read_manifest(manifest)
        rows = list(_csv.DictReader(manifest.open(encoding="utf-8")))
        for meta in docs:
            if meta.doc_type != "statute" or meta.doc_id.startswith("LAW-SAMPLE"):
                continue
            if args.only and not any(o in meta.title for o in args.only):
                continue
            info = api.find_law(meta.title, settings.corpus.law_date)
            path = settings.resolve(settings.paths.raw_dir) / meta.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(api.law_text(info["법령일련번호"], str(info.get("시행일자", ""))), encoding="utf-8")
            for r in rows:  # 문서 목록에 시행일자·수집일 기록
                if r["doc_id"] == meta.doc_id:
                    r["version"] = f"시행 {info.get('시행일자')} (공포 {info.get('공포일자')}, MST {info['법령일련번호']})"
                    r["collected_at"] = _time.strftime("%Y-%m-%d")
            print(f"{meta.title}: 시행 {info.get('시행일자')} → {path.relative_to(ROOT)}")
        with manifest.open("w", encoding="utf-8", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    elif args.cmd == "build-topics":
        from kant_rag.ingest.cases import build_topics
        from kant_rag.ingest.loader import read_manifest

        raw = settings.resolve(settings.paths.raw_dir)
        statutes = [(m, (raw / m.path).read_text(encoding="utf-8"))
                    for m in read_manifest(settings.resolve(settings.paths.manifest))
                    if m.doc_type == "statute" and not m.doc_id.startswith("LAW-SAMPLE") and (raw / m.path).exists()]
        topics = build_topics(statutes, settings.corpus.topic_level)
        out = ROOT / "data" / "cases" / "topics.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# 판례 검색 주제어 — 수집 법령의 편/장/절/관·조문 제목에서 자동 생성 (시험 문장 사용 금지)\n"
                       + "\n".join(topics) + "\n", encoding="utf-8")
        print(f"법령 {len(statutes)}개 → 주제어 {len(topics)}개 → {out.relative_to(ROOT)}")

    elif args.cmd == "fetch-cases":
        from kant_rag.ingest.cases import collect_cases
        from kant_rag.ingest.lawapi import LawAPI

        topics_path = ROOT / "data" / "cases" / "topics.txt"
        topics = [t.strip() for t in topics_path.read_text(encoding="utf-8").splitlines()
                  if t.strip() and not t.startswith("#")]
        if args.limit_topics:
            topics = topics[: args.limit_topics]
        c = settings.corpus
        stats = collect_cases(LawAPI(), topics, settings.resolve(settings.paths.raw_dir) / "cases" / "cases.jsonl",
                              c.case_date_from, c.case_date_to, c.cases_per_topic, kinds=c.case_kinds)
        print(json.dumps(stats, ensure_ascii=False))

    elif args.cmd == "build-index":
        from kant_rag.ingest.build_index import build_index

        print(json.dumps(build_index(settings), ensure_ascii=False, indent=2))

    elif args.cmd == "import-cases":
        import shutil
        import tempfile

        from kant_rag.ingest.case_import import import_cases

        missing = [p for p in args.inputs if not Path(p).exists()]
        if missing:
            raise SystemExit("경로를 찾을 수 없습니다: " + ", ".join(missing)
                             + "\n→ 판례 파일이 있는 폴더 경로를 확인하세요 (cmd: dir /s /b /ad <상위폴더>\\*prec*)")
        c = settings.corpus
        cases_dir = settings.resolve(settings.paths.raw_dir) / "cases"
        target = cases_dir
        if args.dry_run:  # 기존 중복 판정은 유지하고 결과는 임시 폴더에
            target = Path(tempfile.mkdtemp())
            for f in cases_dir.glob("*.jsonl"):
                shutil.copy(f, target / f.name)
        stats = import_cases([Path(p) for p in args.inputs], target, c.case_date_to, c.case_kinds, c.case_codes,
                             args.source)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if stats.get("file_mb_over_90"):
            print("⚠ 90MB 넘는 파일이 있습니다 — GitHub 업로드 전 알려 주세요 (파일 분할 필요)")
        if args.dry_run:
            shutil.rmtree(target, ignore_errors=True)
            print("(dry-run: 저장하지 않음)")
        else:
            print("다음: uv run kant-rag build-index")

    elif args.cmd == "find":
        from kant_rag.ingest.build_index import build_chunks

        kws = [k.replace(" ", "") for k in args.keywords]
        hits = [c for c in build_chunks(settings) if all(k in c.text.replace(" ", "") for k in kws)]
        print(f"'{' + '.join(args.keywords)}' 포함 청크 {len(hits)}개" + (f" (앞 {args.limit}개)" if len(hits) > args.limit else ""))
        for c in hits[: args.limit]:
            body = c.text.replace("\n", " ")
            m = re.search(r"\s*".join(map(re.escape, kws[0])), body)
            pos = m.start() if m else 0
            print(f"\n{c.chunk_id}  |  {c.location()}\n  …{body[max(0, pos - 60): pos + 200]}…")

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

    elif args.cmd == "tag-traps":
        from collections import Counter

        from kant_rag.mcq.io import BarEvalSet
        from kant_rag.mcq.traps import AUTO, TRAP_DESCRIPTIONS, auto_traps

        for name in ("dev", "test"):
            path = ROOT / "eval" / f"{name}.json"
            es = BarEvalSet.model_validate_json(path.read_text(encoding="utf-8"))
            if es.frozen:
                print(f"skip (frozen): {name}")
                continue
            for q in es.items:
                unknown = [t for t in q.traps if t not in TRAP_DESCRIPTIONS]
                if unknown:
                    print(f"  ⚠ {q.id}: 정의되지 않은 태그 {unknown} (mcq/traps.py 참고)")
                q.traps = auto_traps(q) + [t for t in q.traps if t not in AUTO]
            path.write_text(es.model_dump_json(indent=2), encoding="utf-8")
            print(name, dict(Counter(t for q in es.items for t in q.traps)))

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
            from kant_rag.mcq.schemas import derive_statement_labels

            n = 0
            for q in obj.items:
                if q.number in key and q.answer != key[q.number]:
                    q.answer = key[q.number]
                    n += 1
                q.statement_labels = derive_statement_labels(q)  # 정답 → 진술별 참/거짓 역산
            path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
            missing = [q.number for q in obj.items if q.answer is None]
            print(f"{path.relative_to(ROOT)}: {n}개 반영, 미기입 {missing}")

    elif args.cmd == "solve":
        from kant_rag.mcq.io import Exam
        from kant_rag.mcq.solver import MCQSolver
        from kant_rag.retrieval.pipeline import RetrievalMode

        from kant_rag.mcq.presets import PRESETS, apply_overrides, parse_sets

        exam = Exam.model_validate_json(Path(args.exam_json).read_text(encoding="utf-8"))
        q = next(x for x in exam.items if x.number == args.number)
        s = apply_overrides(settings, {**PRESETS.get(args.preset or "", {}), **parse_sets(args.sets)})
        rec = MCQSolver(s).solve(q, RetrievalMode(args.mode))
        print(f"[문 {q.number}] form={q.form} polarity={q.polarity} status={rec['status']}")
        for k, j in (rec.get("judgments") or {}).items():
            src = " [지식]" if j.get("source") == "knowledge" else ""
            print(f"  {k}: {j['verdict']} ({j['confidence']:.2f}){src} {j['reason'][:80]} {j['cited_chunk_ids']}")
        if rec.get("context_expansions"):
            print("확장 근거:", rec["context_expansions"])
        print("예측:", rec.get("predicted"), "| 보기 점수:", rec.get("option_scores"))
        if args.show_answer:
            print("정답:", q.answer)
        print("timing_ms:", rec["timing_ms"])

    elif args.cmd == "solve-text":
        from kant_rag.mcq.textsolve import solve_text

        if args.preset not in PRESETS_NAMES():
            raise SystemExit(f"프리셋 이름: {', '.join(PRESETS_NAMES())}")
        text = sys.stdin.read() if args.text_path == "-" else Path(args.text_path).read_text(encoding="utf-8-sig")
        solve_text(settings, text, args.preset, args.mode, args.answers, args.label, args.sets)

    elif args.cmd == "progress":
        from kant_rag.mcq.progress import watch

        try:
            watch(settings.resolve(settings.paths.results_dir), args.label, args.watch, args.total)
        except KeyboardInterrupt:
            pass

    elif args.cmd == "eval":
        from kant_rag.mcq.evaluate import run_bar_eval
        from kant_rag.retrieval.pipeline import RetrievalMode

        from kant_rag.mcq.presets import PRESETS, apply_overrides, parse_sets

        s = settings.model_copy(deep=True)
        if s.optimization.cache.enabled:
            raise SystemExit("품질 비교 실행에서는 캐시를 꺼야 합니다 (optimization.cache.enabled=false)")
        s.optimization.rewrite.enabled = args.rewrite
        if args.preset and args.preset not in PRESETS:
            raise SystemExit(f"프리셋 이름: {', '.join(PRESETS)}")
        overrides = {**PRESETS.get(args.preset or "", {}), **parse_sets(args.sets)}
        s = apply_overrides(s, overrides)
        meta = {"preset": args.preset, "overrides": overrides}
        print("설정:", meta)
        print("saved:", run_bar_eval(s, Path(args.eval_path), [RetrievalMode(m) for m in args.modes], args.label,
                                     meta=meta))


def PRESETS_NAMES() -> list[str]:
    from kant_rag.mcq.presets import PRESETS

    return list(PRESETS)


if __name__ == "__main__":
    main()
