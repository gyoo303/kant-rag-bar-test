"""gpt-6-luna가 어떤 결정성 파라미터를 받는지 실제 호출로 확인한다."""
import sys
from lawqa.shared.settings import load_settings
from langchain_openai import ChatOpenAI

s = load_settings("base")
key = s.secrets.require("openai_api_key")
MODEL = s.models.generation
MSG = [("human", "숫자 1부터 5 중 하나만 골라 숫자만 답해.")]

cases = {
    "기준(파라미터 없음)": {},
    "temperature=0": {"temperature": 0},
    "temperature=1": {"temperature": 1},
    "top_p=0.01": {"top_p": 0.01},
    "top_p=1": {"top_p": 1},
    "seed=42": {"seed": 42},
    "seed+top_p": {"seed": 42, "top_p": 0.01},
    "presence_penalty=0": {"presence_penalty": 0},
    "logprobs=True": {"logprobs": True},
}
for name, kw in cases.items():
    try:
        llm = ChatOpenAI(model=MODEL, api_key=key, timeout=60, max_retries=0, **kw)
        r = llm.invoke(MSG)
        meta = r.response_metadata or {}
        fp = meta.get("system_fingerprint")
        print(f"  OK   {name:24s} -> {r.content!r:12s} fingerprint={fp}")
    except Exception as e:
        msg = str(e).replace("\n", " ")
        print(f"  거부 {name:24s} -> {type(e).__name__}: {msg[:150]}")
    sys.stdout.flush()
