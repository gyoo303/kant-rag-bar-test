"""seed가 실제로 출력을 고정하는지 센다. 짧고 변동 여지가 있는 질문으로 N번씩."""
import sys
from collections import Counter
from lawqa.shared.settings import load_settings
from langchain_openai import ChatOpenAI

s = load_settings("base")
key = s.secrets.require("openai_api_key")
MODEL = s.models.generation
MSG = [("human", "아무 한국 도시 이름 하나만 답해. 설명 없이 이름만.")]
N = 8

def run(label, **kw):
    out = []
    for _ in range(N):
        llm = ChatOpenAI(model=MODEL, api_key=key, timeout=60, max_retries=1, **kw)
        out.append(llm.invoke(MSG).content.strip())
    c = Counter(out)
    top = c.most_common(1)[0]
    print(f"  {label:18s} 서로 다른 답 {len(c)}가지 / {N}회   최빈 {top[0]!r} {top[1]}회   {dict(c)}")
    sys.stdout.flush()

run("seed 없음")
run("seed=42", seed=42)
run("seed=42 (재시도)", seed=42)
run("seed=7", seed=7)
