"""RAGAS 보조 지표 (교안 7-3, 7-4). 필수 지표(Hit@5 등)와 별도로 보고한다.

검색: LLMContextPrecisionWithReference, LLMContextRecall
생성: Faithfulness, ResponseRelevancy
심사위원: config.JUDGE_MODEL(팀 통일 gpt-6-luna) + text-embedding-3-small  (교안 7장은 gpt-4o-mini)
입력: results/<batch>/<구성>/runs.jsonl + eval/<split>.json  → 같은 폴더에 ragas.csv
"""

from __future__ import annotations

import json
from pathlib import Path

from civil_rag import config
from civil_rag.evaluation.dataset import load_eval
from civil_rag.ingest.build import load_chunks


def run_ragas(run_dir: Path, split: str) -> Path:
    from langchain.chat_models import init_chat_model
    from langchain_openai import OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    _, items = load_eval(split)
    by_id = {it["id"]: it for it in items}
    texts = {c.chunk_id: c.text for c in load_chunks()}

    rows = []
    for line in (run_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        item = by_id.get(rec["question_id"])
        if not item or item.get("type") == "no_evidence" or not rec.get("retrieval"):
            continue  # 근거 없음 문항·LLM 단독은 RAGAS 대상에서 제외
        reference = item.get("expected_answer", "")
        if item.get("expected_facts"):
            reference += "\n" + "\n".join(item["expected_facts"])
        rows.append({
            "user_input": item["question"],
            "retrieved_contexts": [texts.get(c["chunk_id"], c.get("excerpt", "")) for c in rec["retrieval"]["final"]],
            "response": rec["answer"].get("answer", ""),
            "reference": reference,
        })
    if not rows:
        raise SystemExit("RAGAS 로 평가할 문항이 없습니다 (검색을 쓰는 구성의 답변 가능 문항만 대상).")

    judge_kwargs = {"temperature": config.LLM_TEMPERATURE} if config.LLM_TEMPERATURE is not None else {}
    judge = LangchainLLMWrapper(init_chat_model(model=config.JUDGE_MODEL, model_provider="openai", **judge_kwargs))
    emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=config.EMBEDDING_MODEL))
    metrics = [
        LLMContextPrecisionWithReference(llm=judge),
        LLMContextRecall(llm=judge),
        Faithfulness(llm=judge),
        ResponseRelevancy(llm=judge, embeddings=emb),
    ]
    result = evaluate(dataset=EvaluationDataset.from_list(rows), metrics=metrics, raise_exceptions=False)
    df = result.to_pandas()
    out = run_dir / "ragas.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(df.drop(columns=["retrieved_contexts", "response", "reference"], errors="ignore").describe().T)
    print(f"RAGAS 결과: {out}")
    return out
