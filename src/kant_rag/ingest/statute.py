"""법령 조문 단위 청킹.

- 청크 ID: `{doc_id}#제750조`, `{doc_id}#제750조의2` (조문 번호 기반 → 청킹 설정과 무관하게 안정적)
- 조문이 chunk_size 보다 길면 항(①②…) 경계에서 나눠 `#제750조-1`, `#제750조-2` …
- 편/장/절 제목은 section 경로로 보존 (예: "제3편 채권 > 제5장 불법행위")
- 국가법령정보센터 본문 텍스트(조문이 '제N조(제목) …' 로 시작하는 행) 형식을 가정합니다.
"""

from __future__ import annotations

import re

from kant_rag.schemas import Chunk, DocumentMeta

ARTICLE = re.compile(r"^\s*(제\s*(\d+)\s*조(?:\s*의\s*(\d+))?)\s*(?:\(([^)]*)\))?")
PART = re.compile(r"^\s*(제\s*\d+\s*(편|장|절|관))\s+(.+)$")
PARAGRAPH = re.compile(r"^\s*[①-⑳]")
PART_LEVEL = {"편": 0, "장": 1, "절": 2, "관": 3}


def _article_key(no: str, sub: str | None) -> str:
    return f"제{int(no)}조" + (f"의{int(sub)}" if sub else "")


def chunk_statute(text: str, meta: DocumentMeta, chunk_size: int = 1200) -> list[Chunk]:
    lines = text.split("\n")
    parts: list[str] = ["", "", "", ""]
    articles: list[dict] = []
    cur: dict | None = None

    def flush():
        if cur and any(ln.strip() for _, ln in cur["lines"]):
            articles.append(cur)

    for no, line in enumerate(lines, start=1):
        pm = PART.match(line)
        if pm and not ARTICLE.match(line):
            flush()
            cur = None
            lvl = PART_LEVEL[pm.group(2)]
            parts[lvl] = f"{pm.group(1).replace(' ', '')} {pm.group(3).strip()}"
            for i in range(lvl + 1, 4):
                parts[i] = ""
            continue
        am = ARTICLE.match(line)
        if am:
            flush()
            cur = {"key": _article_key(am.group(2), am.group(3)), "title": (am.group(4) or "").strip(),
                   "section": " > ".join(p for p in parts if p), "lines": []}
        if cur is not None:
            cur["lines"].append((no, line))
    flush()

    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    for art in articles:
        key = art["key"]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:  # 삭제 조문 등으로 같은 번호가 반복되면 접미사
            key = f"{key}~{seen[key]}"
        groups: list[list[tuple[int, str]]] = [[]]
        size = 0
        for no, ln in art["lines"]:
            if groups[-1] and size + len(ln) > chunk_size and PARAGRAPH.match(ln):
                groups.append([])
                size = 0
            groups[-1].append((no, ln))
            size += len(ln) + 1
        label = f"{key}({art['title']})" if art["title"] else key
        for g_idx, g in enumerate(groups, start=1):
            body = "\n".join(ln for _, ln in g if ln.strip())
            if not body:
                continue
            cid = f"{meta.doc_id}#{key}" + (f"-{g_idx}" if len(groups) > 1 else "")
            head = f"[{meta.title}] {label}" + ("" if g_idx == 1 else " (계속)")
            chunks.append(Chunk(
                chunk_id=cid, doc_id=meta.doc_id, title=meta.title, text=f"{head}\n{body}",
                section=" > ".join(x for x in (art["section"], label) if x),
                line_start=g[0][0], line_end=g[-1][0],
                metadata={"source": meta.source, "version": meta.version, "doc_type": "statute",
                          "article": key, "article_title": art["title"]},
            ))
    return chunks
