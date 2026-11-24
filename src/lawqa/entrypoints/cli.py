"""명령줄 진입점 `python -m lawqa <group> <command>` (04-interfaces-api §3, CONV-06).

아직 구현되지 않은 명령은 담당 티켓을 알려 주고 종료 코드 1로 끝난다.
종료 코드: 0 성공, 1 입력·형식 오류, 2 외부·DB 연결 실패, 3 규칙 위반.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from importlib import resources
from pathlib import Path

import openai
import psycopg

from lawqa.corpus.application.import_service import MissingStatuteFileError
from lawqa.corpus.application.index_service import IndexingError
from lawqa.corpus.infrastructure import (
    build_chunk_query_service,
    build_import_service,
    build_index_service,
    chunking_policy,
)
from lawqa.evaluation.domain.errors import InvalidEvalDataError, RuleViolationError
from lawqa.evaluation.domain.models import Split
from lawqa.evaluation.domain.run import RunKind
from lawqa.evaluation.infrastructure import FREEZE_FILE, build_freeze_service, build_run_service
from lawqa.evaluation.infrastructure.git_info import GitCommandError
from lawqa.shared.clock import SystemClock
from lawqa.shared.db import connect, init_schema
from lawqa.shared.logging_setup import configure_logging
from lawqa.shared.settings import RUN_CONFIGS, SettingsError, load_settings
from lawqa.shared.smoke import LiveSmokeProbes, run_smoke, summary_lines, write_report
from lawqa.shared.versioning import sha256_of

# prompt_sha 대상 프롬프트 (04-interfaces-api §5, CONV-09): (패키지, 파일 이름)
PROMPT_FILES = (
    ("lawqa.answering.infrastructure", "prompts/answer.txt"),
    ("lawqa.retrieval.infrastructure", "prompts/rewrite.txt"),
)

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_EXTERNAL_ERROR = 2
EXIT_RULE_VIOLATION = 3

RUN_CONFIG_CHOICES = ("A", "B", "C", "C+R")

# (그룹, 명령) → 구현할 티켓 (임시: 명령을 구현하는 티켓에서 항목을 지운다)
_PENDING_TICKETS: dict[tuple[str, str | None], str] = {
    ("eval", "grade"): "TKT-BE-M4-01",
    ("eval", "review"): "TKT-BE-M4-01",
    ("eval", "metrics"): "TKT-BE-M4-02",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lawqa",
        description="민법 선택형 문항 RAG 에이전트 명령줄 (04-interfaces-api §3)",
    )
    groups = parser.add_subparsers(dest="group", required=True, metavar="<group>")

    db = groups.add_parser("db", help="DB 스키마")
    db_cmd = db.add_subparsers(dest="command", required=True, metavar="<command>")
    db_cmd.add_parser("init", help="API-01 스키마·확장 생성")

    corpus = groups.add_parser("corpus", help="원문 가져오기·색인")
    corpus_cmd = corpus.add_subparsers(dest="command", required=True, metavar="<command>")
    corpus_import = corpus_cmd.add_parser("import", help="API-02 law_collector 출력 가져오기")
    corpus_import.add_argument("--raw-dir", default=None, help="기본값은 설정 [paths] raw_dir")
    corpus_index = corpus_cmd.add_parser("index", help="API-03 청킹·임베딩·색인")
    corpus_index.add_argument("--config", default="base")

    check = groups.add_parser("check", help="시작 전 점검")
    check_cmd = check.add_subparsers(dest="command", required=True, metavar="<command>")
    check_cmd.add_parser("smoke", help="API-04 생성·임베딩·GPU 재정렬·검색 시험 호출")

    ask = groups.add_parser("ask", help="API-05 문항 하나 답하기")
    ask.add_argument("--config", choices=RUN_CONFIG_CHOICES, required=True)
    ask.add_argument("--file", required=True, help='{"stem": "...", "options": [5개]} JSON 파일')

    evaluation = groups.add_parser("eval", help="평가")
    eval_cmd = evaluation.add_subparsers(dest="command", required=True, metavar="<command>")
    freeze = eval_cmd.add_parser("freeze", help="API-06 고정 기록")
    freeze.add_argument("--stage", choices=("criteria", "final"), required=True)
    run = eval_cmd.add_parser("run", help="API-07 일괄 실행")
    run.add_argument("--split", choices=("dev", "test"), required=True)
    run.add_argument("--config", choices=RUN_CONFIG_CHOICES, required=True)
    run.add_argument("--kind", choices=("main", "warmup", "retry", "extra"), required=True)
    run.add_argument("--retry-of", default=None)
    run.add_argument("--resume", default=None)
    run.add_argument("--only", default=None, help="질문 ID 쉼표 목록")
    run.add_argument("--dry-run", action="store_true", help="실행 전 검사만 하고 종료")
    grade = eval_cmd.add_parser("grade", help="API-08 LLM 1차 채점")
    grade.add_argument("--run", required=True)
    review = eval_cmd.add_parser("review", help="API-09 사람 판정 가져오기")
    review.add_argument("--run", required=True)
    review.add_argument("--csv", required=True)
    metrics = eval_cmd.add_parser("metrics", help="API-10 지표 계산")
    metrics.add_argument("--runs", required=True, help="실행 ID 쉼표 목록")

    return parser


def _use_utf8_console() -> None:
    """Windows 콘솔(cp949)에서도 한글 메시지가 깨지지 않게 표준 출력을 UTF-8로 맞춘다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _cmd_db_init(args: argparse.Namespace) -> int:
    """API-01: 스키마·확장 생성 (`shared.db.init_schema`)."""
    try:
        url = load_settings("base").secrets.require("database_url")
    except SettingsError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        with connect(url) as conn:
            init_schema(conn)
            dbname = conn.info.dbname
    except psycopg.OperationalError as exc:
        print(f"DB 연결 실패: {exc}".strip(), file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    print(
        f"db init 완료: 데이터베이스 {dbname}에 vector 확장과 표를 만들었습니다(이미 있으면 유지)."
    )
    return EXIT_OK


def _cmd_check_smoke(args: argparse.Namespace) -> int:
    """API-04: 시작 전 점검. 결과는 results/smoke/에 기록하고 요약을 출력한다."""
    try:
        settings = load_settings("base")
    except SettingsError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    clock = SystemClock()
    report = run_smoke(settings, LiveSmokeProbes(settings), clock)
    path = write_report(report, settings.paths.results_dir, clock)
    for line in summary_lines(report):
        print(line)
    print(f"기록: {path}")
    return EXIT_OK if report.ok else EXIT_EXTERNAL_ERROR


def _cmd_corpus_import(args: argparse.Namespace) -> int:
    """API-02: law_collector 출력 가져오기. 건너뛴 건이 있어도 0(경고 출력)."""
    try:
        settings = load_settings("base")
        url = settings.secrets.require("database_url")
    except SettingsError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    raw_dir = Path(args.raw_dir) if args.raw_dir else settings.paths.raw_dir
    try:
        with connect(url) as conn:
            report = build_import_service(conn).import_files(raw_dir)
    except MissingStatuteFileError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except psycopg.Error as exc:
        print(f"DB 오류: {exc}".strip(), file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    print(f"가져온 문서 {report.imported}건, 건너뜀 {report.skipped}건")
    reasons: dict[str, int] = {}
    for issue in report.issues:
        reasons[issue.reason] = reasons.get(issue.reason, 0) + 1
    for reason, count in sorted(reasons.items()):
        print(f"  건너뜀 {reason}: {count}건")
    print("제외(오류 아님): " + ", ".join(f"{k}={v}" for k, v in report.excluded.items()))
    if report.ignored_files:
        print(f"무시한 범위 밖 법령 파일: {', '.join(report.ignored_files)}")
    print(f"corpus_version={report.corpus_version}")
    if report.skipped:
        print(
            f"경고: {report.skipped}건을 건너뛰었습니다. 이 원문의 색인은 불완전으로 표시됩니다.",
            file=sys.stderr,
        )
    return EXIT_OK


def _cmd_corpus_index(args: argparse.Namespace) -> int:
    """API-03: 청킹·임베딩·색인. GATE-10 형식 한 줄을 출력한다."""
    try:
        settings = load_settings(args.config)
        url = settings.secrets.require("database_url")
        with connect(url) as conn:
            service = build_index_service(conn, settings, database_url=url)
            result = service.build_index(chunking_policy(settings))
    except SettingsError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except IndexingError as exc:
        print(f"색인 실패: {exc}", file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    except (psycopg.Error, openai.OpenAIError) as exc:
        print(f"외부 호출 실패: {type(exc).__name__}: {exc}".strip(), file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    if result.already_existed:
        print(f"이미 있음: 판본 {result.version.index_version}을 다시 만들지 않습니다.")
    print(result.summary_line())
    return EXIT_OK


def _cmd_ask(args: argparse.Namespace) -> int:
    """API-05: 문항 하나 답하기. 오류 결과도 종료 코드 0(결과 종류로 표시, ADR-004)."""
    from lawqa.entrypoints.composition import build_answer_runtime

    try:
        item = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"입력 파일 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        url = load_settings("base").secrets.require("database_url")
        with connect(url) as conn:
            runtime = build_answer_runtime(conn, url)
            warning = runtime.index_warning()
            if warning:
                print(f"경고: {warning}", file=sys.stderr)
            envelope = runtime.service.answer(item, args.config)
    except SettingsError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except psycopg.OperationalError as exc:
        print(f"DB 연결 실패: {exc}".strip(), file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    print(json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2))
    return EXIT_OK


def _config_shas() -> dict[str, str]:
    return {name: load_settings(name).config_sha for name in RUN_CONFIGS}


def _prompt_sha() -> str:
    """답변·리라이트 프롬프트 파일 내용의 해시(SEQ-06). 파일이 없으면 입력 오류."""
    parts: list[str] = []
    for package, name in PROMPT_FILES:
        path = resources.files(package).joinpath(name)
        if not path.is_file():
            raise InvalidEvalDataError(
                f"프롬프트 파일이 아직 없습니다: {package}/{name} (TKT-BE-M3-03·M3-04에서 생성)"
            )
        parts.append(f"{name}:{sha256_of(path.read_bytes())}")
    return sha256_of("\n".join(parts).encode())


def _complete_index_version() -> str:
    """가장 최근 완료 색인 판본(`eval freeze --stage final`). 없으면 입력 오류."""
    url = load_settings("base").secrets.require("database_url")
    with connect(url) as conn:
        version = build_chunk_query_service(conn).latest_complete_version()
    if version is None:
        raise InvalidEvalDataError("완료된 색인 판본이 없습니다. 먼저 corpus index를 실행하세요.")
    return version.index_version


def _cmd_eval_freeze(args: argparse.Namespace) -> int:
    """API-06: 고정 기록(`eval/FREEZE.json`). git 태그는 사람이 단다."""
    try:
        settings = load_settings("base")
        service = build_freeze_service(
            settings,
            config_shas=_config_shas,
            prompt_sha=_prompt_sha,
            index_version=_complete_index_version,
        )
        record = service.freeze(args.stage)
    except RuleViolationError as exc:
        print(f"규칙 위반: {exc}", file=sys.stderr)
        return EXIT_RULE_VIOLATION
    except (SettingsError, InvalidEvalDataError, GitCommandError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    freeze_path = settings.paths.eval_dir / FREEZE_FILE
    tag = f"freeze-{record.stage.value}"
    print(f"고정 완료({record.stage.value}): {freeze_path} (frozen_at {record.frozen_at})")
    print(f"다음: git add {freeze_path.as_posix()} && git commit, 그 뒤 git tag {tag}")
    return EXIT_OK


def _cmd_eval_run(args: argparse.Namespace) -> int:
    """API-07: 일괄 실행. 규칙 위반 3, 입력 오류 1, DB 연결 실패 2."""
    from lawqa.entrypoints.composition import AnswerRuntime, build_answer_runtime

    only = [q.strip() for q in args.only.split(",") if q.strip()] if args.only else None
    try:
        settings = load_settings("base")
        split, kind = Split(args.split), RunKind(args.kind)
        freeze = build_freeze_service(
            settings,
            config_shas=_config_shas,
            prompt_sha=_prompt_sha,
            index_version=_complete_index_version,
        )
        url = settings.secrets.require("database_url")
        with connect(url) as conn:
            runtime_cache: list[AnswerRuntime] = []

            def runtime() -> AnswerRuntime:
                if not runtime_cache:
                    runtime_cache.append(build_answer_runtime(conn, url, settings=settings))
                    warning = runtime_cache[0].index_warning()
                    if warning:
                        print(f"경고: {warning}", file=sys.stderr)
                return runtime_cache[0]

            def versions_for(config_name: str) -> dict[str, str]:
                version = runtime().index_version
                models = load_settings(config_name).models
                return {
                    "corpus": version.corpus_version if version else "",
                    "index": version.index_version if version else "",
                    "config_sha": load_settings(config_name).config_sha,
                    "prompt_sha": _prompt_sha(),
                    "gen_model": models.generation,
                    "embedding_model": f"{models.embedding}/{models.embedding_dim}",
                    "reranker_model": models.reranker,
                }

            service = build_run_service(
                settings,
                current_freeze=freeze.current,
                versions_for=versions_for,
                answerer=lambda: runtime().service,
            )
            options = {"retry_of": args.retry_of, "resume_run_id": args.resume, "only": only}
            if args.dry_run:
                plan = service.plan(split, args.config, kind, **options)
                print(f"검사 통과(--dry-run): 실행 {plan.run_id}, 문항 {len(plan.question_ids)}개")
                if plan.question_ids:
                    print("대상: " + ", ".join(plan.question_ids))
                return EXIT_OK
            summary = service.run(split, args.config, kind, **options)
    except RuleViolationError as exc:
        print(f"규칙 위반: {exc}", file=sys.stderr)
        return EXIT_RULE_VIOLATION
    except (SettingsError, InvalidEvalDataError, GitCommandError, FileExistsError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except psycopg.OperationalError as exc:
        print(f"DB 연결 실패: {exc}".strip(), file=sys.stderr)
        return EXIT_EXTERNAL_ERROR
    plan = summary.plan
    run_dir = settings.paths.results_dir / plan.run_id
    counts = ", ".join(f"{k} {v}" for k, v in sorted(summary.outcomes.items())) or "없음"
    resumed = f"(이어 하기, 이미 기록 {len(plan.already_done)}건)" if plan.resumed else ""
    print(f"실행 {plan.run_id}{resumed}: 이번 기록 {summary.recorded}건 — {counts}")
    print(f"기록: {run_dir.as_posix()}/records.jsonl")
    return EXIT_OK


_HANDLERS: dict[tuple[str, str | None], Callable[[argparse.Namespace], int]] = {
    ("db", "init"): _cmd_db_init,
    ("corpus", "import"): _cmd_corpus_import,
    ("corpus", "index"): _cmd_corpus_index,
    ("check", "smoke"): _cmd_check_smoke,
    ("ask", None): _cmd_ask,
    ("eval", "freeze"): _cmd_eval_freeze,
    ("eval", "run"): _cmd_eval_run,
}


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_console()
    configure_logging()
    args = build_parser().parse_args(argv)
    key = (args.group, getattr(args, "command", None))
    handler = _HANDLERS.get(key)
    if handler is not None:
        return handler(args)
    ticket = _PENDING_TICKETS.get(key)
    label = " ".join(part for part in key if part)
    if ticket is not None:
        print(f"미구현: `{label}` 명령은 {ticket}에서 구현합니다.", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"알 수 없는 명령: {label}", file=sys.stderr)
    return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
