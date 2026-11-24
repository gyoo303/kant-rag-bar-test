"""너무 긴 청크 분할 (임베딩 max_tokens 에서 잘리지 않도록).

- 첫 줄(머리: 법령명·조문 / 판례 사건·판결요지 번호)을 각 조각에 반복해 붙여 출처를 유지
- 행 단위로 묶고, 한 행이 너무 길면 문장(…다. / …음.) 경계에서 다시 나눔
- 나뉜 조각 ID: `<원 ID>~1`, `~2` … (나뉘지 않은 청크는 ID 그대로)
"""

from __future__ import annotations

import re

from kant_rag.schemas import Chunk

SENT = re.compile(r"(?<=[다음함임]\.)\s+|(?<=[다음함임]\.)(?=\S)")


def _units(body: str, max_chars: int) -> list[str]:
    out: list[str] = []
    for line in body.split("\n"):
        if len(line) <= max_chars:
            out.append(line)
            continue
        for sent in SENT.split(line):  # 문장 단위, 그래도 길면 고정 길이
            while len(sent) > max_chars:
                out.append(sent[:max_chars])
                sent = sent[max_chars:]
            if sent.strip():
                out.append(sent)
    return [u for u in out if u.strip()]


def split_long(chunk: Chunk, max_chars: int) -> list[Chunk]:
    if len(chunk.text) <= max_chars:
        return [chunk]
    head, _, body = chunk.text.partition("\n")
    budget = max(200, max_chars - len(head) - 12)
    pieces: list[list[str]] = [[]]
    size = 0
    for u in _units(body, budget):
        if pieces[-1] and size + len(u) + 1 > budget:
            pieces.append([])
            size = 0
        pieces[-1].append(u)
        size += len(u) + 1
    n = len(pieces)
    return [
        chunk.model_copy(update={
            "chunk_id": f"{chunk.chunk_id}~{i}",
            "text": f"{head} ({i}/{n})\n" + "\n".join(p),
            "metadata": {**chunk.metadata, "part": i, "parts": n, "parent_id": chunk.chunk_id},
        })
        for i, p in enumerate(pieces, start=1)
    ]
