"""2026 선택형 민사법 70문항을 구현된 RAG로 푼다 (사전 실험, 본 평가 아님).

평가 무결성(C-09): **정답표(DOC-05)를 읽지 않는다.** 채점은 `grade_exam.py`가 따로 한다.
결과는 `results/`(본 평가 기록 자리)가 아니라 scratchpad에 JSONL로 남긴다.

한 줄 = 문항 하나. 이어 하기: 이미 기록된 번호는 건너뛴다.
사용: python run_exam.py <items.json> <out.jsonl> [config]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from lawqa.answering.infrastructure.generator import (
    AnswerPrompt,
    OpenAIAnswerGenerator,
    chat_model,
)
from lawqa.entrypoints.composition import build_answer_runtime
from lawqa.shared.db import connect
from lawqa.shared.settings import load_settings


def forced_generator(settings, prompt_file: Path) -> OpenAIAnswerGenerator:
    """시험 전용 프롬프트로 만든 생성기. 저장소의 `prompts/answer.txt`는 건드리지 않는다.

    검색·재정렬·리라이트 경로는 운영과 같고, 바뀌는 것은 프롬프트 문구뿐이다.
    """
    chat = chat_model(
        settings.models.generation,
        settings.secrets.require("openai_api_key"),
        settings.timeouts.generation_s,
    )
    return OpenAIAnswerGenerator(chat, AnswerPrompt(prompt_file.read_text(encoding="utf-8")))


def done_numbers(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            seen.add(json.loads(line)["no"])
    return seen


def main() -> int:
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    config = sys.argv[3] if len(sys.argv) > 3 else "C+R"
    prompt_file = Path(sys.argv[4]) if len(sys.argv) > 4 else None

    skip = done_numbers(out)
    todo = [i for i in items if i["no"] not in skip]
    print(f"문항 {len(items)}개 중 {len(todo)}개 실행 (이미 완료 {len(skip)}개), 구성 {config}",
          file=sys.stderr, flush=True)

    settings = load_settings("base")
    url = settings.secrets.require("database_url")
    generator = forced_generator(settings, prompt_file) if prompt_file else None
    if generator:
        print(f"시험 전용 프롬프트 사용: {prompt_file} (sha {generator.prompt_sha[:12]})",
              file=sys.stderr, flush=True)
    started = time.monotonic()
    with connect(url) as conn:
        runtime = build_answer_runtime(conn, url, settings=settings, generator=generator)
        warning = runtime.index_warning()
        if warning:
            print(f"경고: {warning}", file=sys.stderr, flush=True)

        with out.open("a", encoding="utf-8") as fp:
            for pos, item in enumerate(todo, start=1):
                t0 = time.monotonic()
                record = None
                for attempt in (1, 2, 3):
                    try:
                        envelope = runtime.service.answer(
                            {"stem": item["stem"], "options": item["options"]}, config
                        )
                        record = {"no": item["no"], "attempt": attempt, **envelope.to_dict()}
                    except Exception as exc:  # 서비스가 변환하지 못한 예외도 기록만 하고 계속
                        record = {
                            "no": item["no"],
                            "attempt": attempt,
                            "config": config,
                            "outcome": "RUNNER_ERROR",
                            "answer_no": None,
                            "error_code": type(exc).__name__,
                            "user_message": str(exc)[:500],
                        }
                    # 모델 호출 자체가 실패해 출력이 없을 때만 다시 시도한다
                    transient = not (record.get("raw_output") or "").strip()
                    if not transient or attempt == 3:
                        break
                    print(f"    재시도 {attempt} (문 {item['no']}: {record.get('error_code')})",
                          file=sys.stderr, flush=True)
                    time.sleep(3)
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                fp.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{pos}/{len(todo)}] 문 {item['no']}: {record['outcome']} "
                    f"answer_no={record.get('answer_no')} {elapsed:.1f}s",
                    file=sys.stderr, flush=True,
                )

    print(f"끝. 총 {time.monotonic() - started:.0f}초, 기록 {out}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
