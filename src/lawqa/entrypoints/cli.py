"""명령줄 진입점 `python -m lawqa <group> <command>` (04-interfaces-api §3, CONV-06).

이 티켓(TKT-BE-M1-01)은 명령 뼈대만 만든다. 아직 구현되지 않은 명령은 담당 티켓을 알려 주고
종료 코드 1로 끝난다. 종료 코드: 0 성공, 1 입력·형식 오류, 2 외부·DB 연결 실패, 3 규칙 위반.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_EXTERNAL_ERROR = 2
EXIT_RULE_VIOLATION = 3

RUN_CONFIG_CHOICES = ("A", "B", "C", "C+R")

# (그룹, 명령) → 구현할 티켓
_PENDING_TICKETS: dict[tuple[str, str | None], str] = {
    ("db", "init"): "TKT-BE-M1-02",
    ("check", "smoke"): "TKT-BE-M1-02",
    ("eval", "freeze"): "TKT-BE-M1-04",
    ("corpus", "import"): "TKT-BE-M2-02",
    ("corpus", "index"): "TKT-BE-M2-02",
    ("ask", None): "TKT-BE-M3-03",
    ("eval", "run"): "TKT-BE-M3-05",
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


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_console()
    args = build_parser().parse_args(argv)
    key = (args.group, getattr(args, "command", None))
    ticket = _PENDING_TICKETS.get(key)
    label = " ".join(part for part in key if part)
    if ticket is not None:
        print(f"미구현: `{label}` 명령은 {ticket}에서 구현합니다.", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"알 수 없는 명령: {label}", file=sys.stderr)
    return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
