from types import SimpleNamespace

import pytest

import kant_rag.generation.llmcall as lc


def test_extract_json_with_trailing_text_and_fences():
    raw = '```json\n{"judgments": {"1": {"verdict": "true"}}}\n```\n설명: {참고} 끝'
    assert lc.extract_json(raw, "judgments")["judgments"]["1"]["verdict"] == "true"
    raw2 = '먼저 {잡음} 이 있고 {"judgments": {}} 그리고 {"other": 1}'
    assert lc.extract_json(raw2, "judgments") == {"judgments": {}}
    with pytest.raises(ValueError):
        lc.extract_json("", "judgments")


def test_retry_on_empty_length(monkeypatch):
    budgets = []

    class LLM:
        def __init__(self, b):
            self.b = b

        def invoke(self, _):
            budgets.append(self.b)
            if self.b < 200:
                return SimpleNamespace(content="", response_metadata={"finish_reason": "length"},
                                       usage_metadata={"input_tokens": 10, "output_tokens": 100,
                                                       "output_token_details": {"reasoning": 100}})
            return SimpleNamespace(content='{"a": 1}', response_metadata={"finish_reason": "stop"},
                                   usage_metadata={"input_tokens": 10, "output_tokens": 150})

    monkeypatch.setattr(lc, "get_chat_model", lambda p, m, b: LLM(b))
    text, calls = lc.call_llm("openai", "m", [], 100)
    assert text == '{"a": 1}' and budgets == [100, 200]
    assert calls[0]["empty"] and calls[0]["reasoning_tokens"] == 100 and calls[1]["attempt"] == 2
