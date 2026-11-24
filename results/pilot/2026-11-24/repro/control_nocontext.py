"""통제 실험: 검색 문서를 전혀 주지 않고 같은 프롬프트로 풀게 한다.

목적 — RAG 실행에서 맞힌 문항을 "문서 없이"도 맞히는지 본다.
   비슷하게 맞힌다 = 정답률이 검색이 아니라 모델의 사전 지식에서 나온 것.
정답표는 읽지 않는다(채점은 grade_exam.py 몫). 저장소 코드·프롬프트는 건드리지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lawqa.answering.infrastructure.generator import (
    AnswerPrompt,
    OpenAIAnswerGenerator,
    chat_model,
)
from lawqa.retrieval.domain.models import ExamItem
from lawqa.shared.settings import load_settings


def main() -> int:
    items = {i["no"]: i for i in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))}
    numbers = [int(n) for n in sys.argv[2].split(",")]
    out = Path(sys.argv[3])
    prompt_file = Path(sys.argv[4])

    s = load_settings("base")
    gen = OpenAIAnswerGenerator(
        chat_model(s.models.generation, s.secrets.require("openai_api_key"), s.timeouts.generation_s),
        AnswerPrompt(prompt_file.read_text(encoding="utf-8")),
    )

    with out.open("w", encoding="utf-8") as fp:
        for no in numbers:
            it = items[no]
            item = ExamItem(stem=it["stem"], options=tuple(it["options"]))
            try:
                model_answer = gen.generate(item, [])  # 문서 0개
                raw = model_answer.raw_output
                pick = json.loads(raw).get("answer")
                outcome = "ANSWERED"
            except Exception as exc:
                raw, pick, outcome = "", None, type(exc).__name__
            fp.write(json.dumps(
                {"no": no, "outcome": outcome, "answer_no": None, "raw_output": raw},
                ensure_ascii=False) + "\n")
            fp.flush()
            print(f"문 {no}: {outcome} pick={pick}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
