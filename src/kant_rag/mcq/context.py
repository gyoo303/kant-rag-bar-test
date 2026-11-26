"""근거 확장 (개선안 A3·A4).

A3 같은 판결의 다른 항목: 판결요지를 항목([1], [2]…) 단위로 청킹해 같은 판결의 전제와 결론이 갈라진다
   (예: 2024다232523 [1]만 검색되고 결론 [2]는 누락). 검색된 판례 항목의 형제 항목 '판시사항'을 짧게 함께 준다.
A4 준용 조문: 정답이 준용 조문에 있는 경우 (예: 상법 제429조 검색 → 제430조가 제186조·제190조를 준용).
   - 정방향: 검색된 조문 본문에 '준용'이 있으면 거기 언급된 조문을 추가
   - 역방향: 같은 법령에서 검색된 조문을 언급하며 '준용'하는 조문을 추가 (그 조문의 정방향 대상까지)
"""

from __future__ import annotations

import re
from collections import defaultdict

from kant_rag.schemas import Chunk

CASE_ITEM = re.compile(r"^(CASE#.+#)(\d+)(?:~(\d+))?$")
ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
ART_RANGE = re.compile(r"제\s*(\d+)\s*조\s*(?:부터|내지)\s*제\s*(\d+)\s*조")


def _art_key(no: str, sub: str | None) -> str:
    return f"제{int(no)}조" + (f"의{int(sub)}" if sub else "")


def referenced_articles(text: str) -> list[str]:
    """'제186조 내지 제189조ㆍ제190조 본문' → [제186조, 제187조, 제188조, 제189조, 제190조] (등장 순서, 중복 제거)."""
    out: dict[str, None] = {}
    spans = []
    for m in ART_RANGE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < b - a <= 30:
            for n in range(a, b + 1):
                out.setdefault(f"제{n}조")
            spans.append(m.span())
    for m in ART.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        out.setdefault(_art_key(m.group(1), m.group(2)))
    return list(out)


def _is_subject(text: str, art_key: str) -> bool:
    """text 에서 art_key 가 준용의 적용 대상인가: '제429조의 소에 관하여 … 준용', '제5조의 경우에 준용' 등."""
    m = re.match(r"제(\d+)조(?:의(\d+))?", art_key)
    num = m.group(1) + (r"\s*조\s*의\s*" + m.group(2) if m.group(2) else r"\s*조")
    pat = rf"제\s*{num}(?!\s*의\s*\d)(?:(?!규정)[^.。]){{0,25}}(에\s*관하여|의\s*경우에|에\s*대하여|에\s*이를)[^.。]{{0,20}}준용"
    return re.search(pat, text) is not None


def _body(chunk: Chunk) -> str:
    return chunk.text.split("\n", 1)[-1]


class ChunkGraph:
    """청크 사이 관계(같은 판결의 항목, 법령 조문·준용) 색인."""

    def __init__(self, chunks_by_id: dict[str, Chunk]):
        self.by_id = chunks_by_id
        self.case_items: dict[str, dict[str, str]] = defaultdict(dict)  # 판결 prefix → 항목번호 → 첫 조각 id
        self.articles: dict[tuple[str, str], list[str]] = defaultdict(list)  # (doc_id, 제N조) → 조각 ids
        self.referrers: dict[tuple[str, str], list[str]] = defaultdict(list)  # (doc_id, 제N조) → 그 조문을 준용하는 조문 키
        self.users: dict[tuple[str, str], list[str]] = defaultdict(list)  # (doc_id, 제N조) → 그 조문을 가져다 쓰는 조문 키 (v6 2-4)
        self.pieces: dict[str, list[str]] = defaultdict(list)  # 판례 항목 → 조각 ids (~1, ~2 …) (v6 2-5)
        for cid, c in chunks_by_id.items():
            m = CASE_ITEM.match(cid)
            if m:
                prefix, item, part = m.group(1), m.group(2), m.group(3)
                if part in (None, "1"):
                    self.case_items[prefix][item] = cid
                if part is not None:
                    self.pieces[prefix + item].append(cid)
                continue
            art = c.metadata.get("article")
            if c.metadata.get("doc_type") == "statute" and art:
                self.articles[(c.doc_id, art)].append(cid)
        for (doc, art), cids in self.articles.items():
            text = " ".join(_body(self.by_id[x]) for x in cids)
            if "준용" in text:
                for ref in referenced_articles(text):
                    # 역방향은 ref 가 '적용 대상'일 때만: "제429조의 소에 관하여 … 준용" (ref 를 가져다 쓰는 조문은 제외)
                    if ref != art and _is_subject(text, ref):
                        self.referrers[(doc, ref)].append(art)
                    elif ref != art:  # "제208조제2항 … 의 규정은 대표이사에 준용한다" (제389조 ③) → 제208조를 쓰는 조문
                        self.users[(doc, ref)].append(art)
        for v in self.pieces.values():
            v.sort(key=lambda x: int(CASE_ITEM.match(x).group(3)))

    # ---------- A3 ----------
    def case_siblings(self, chunk_ids: list[str], per_case: int = 2, head_chars: int = 300,
                      max_total: int = 6) -> list[tuple[str, str]]:
        """검색된 판례 항목의 같은 판결 다른 항목 → [(청크 id, 머리줄+판시사항 요약)]."""
        out: dict[str, str] = {}
        for cid in chunk_ids:
            m = CASE_ITEM.match(cid)
            if not m:
                continue
            prefix, item = m.group(1), m.group(2)
            seen_items = {CASE_ITEM.match(x).group(2) for x in chunk_ids if x.startswith(prefix) and CASE_ITEM.match(x)}
            n = 0
            for other_item, sib in sorted(self.case_items.get(prefix, {}).items(), key=lambda kv: int(kv[0])):
                if other_item in seen_items or sib in out:
                    continue
                lines = self.by_id[sib].text.split("\n")
                head = lines[0]
                issue = next((ln for ln in lines[1:] if ln.startswith("판시사항")), lines[1] if len(lines) > 1 else "")
                out[sib] = (head + "\n" + issue)[:head_chars]
                n += 1
                if n >= per_case:
                    break
            if len(out) >= max_total:  # 상위 순위 근거의 형제부터, 문항 전체 상한
                break
        return list(out.items())[:max_total]

    # ---------- 긴 조문의 다른 조각 (v4) ----------
    def statute_parts(self, chunk_ids: list[str], max_total: int = 6) -> list[str]:
        """항 단위로 나뉜 조문(LAW-COMM#제542조의12-1, -2 …)의 한 조각이 검색되면 같은 조문의 나머지 조각."""
        have = set(chunk_ids)
        out: list[str] = []
        for cid in chunk_ids:
            c = self.by_id.get(cid)
            if c is None or c.metadata.get("doc_type") != "statute":
                continue
            parts = self.articles.get((c.doc_id, c.metadata.get("article")), [])
            if len(parts) < 2:
                continue
            for x in parts:
                if x not in have and x not in out:
                    out.append(x)
                    if len(out) >= max_total:
                        return out
        return out

    # ---------- A4 ----------
    def expand_references(self, chunk_ids: list[str], max_add: int = 8) -> list[str]:
        """검색된 조문의 준용 관계를 따라 추가할 조문 청크 ids (이미 있는 것 제외)."""
        have = set(chunk_ids)
        reverse: list[tuple[str, str]] = []  # 우선: 이 조문에 다른 규정을 준용하는 조문과 그 준용 대상
        forward: list[tuple[str, str]] = []  # 다음: 이 조문이 준용하는 조문
        for cid in chunk_ids:
            c = self.by_id.get(cid)
            if c is None or c.metadata.get("doc_type") != "statute":
                continue
            doc, art = c.doc_id, c.metadata.get("article")
            if not art:
                continue
            for ref_art in self.referrers.get((doc, art), []):
                reverse.append((doc, ref_art))
                ref_text = " ".join(_body(self.by_id[x]) for x in self.articles.get((doc, ref_art), []))
                reverse += [(doc, r) for r in referenced_articles(ref_text) if r not in (ref_art, art)]
            body = _body(c)
            if "준용" in body:
                forward += [(doc, r) for r in referenced_articles(body) if r != art]
        keys = reverse + forward
        out: list[str] = []
        for key in dict.fromkeys(keys):
            for x in self.articles.get(key, []):
                if x not in have and x not in out:
                    out.append(x)
            if len(out) >= max_add:
                break
        return out[:max_add]

    # ---------- v6 ----------
    def statute_users(self, chunk_ids: list[str], max_total: int = 12) -> list[str]:
        """2-4 역방향 준용: 검색된 조문을 '가져다 쓰는' 조문 청크 (예: 제208조 → 제389조 ③ 대표이사에 준용)."""
        have = set(chunk_ids)
        out: list[str] = []
        for cid in chunk_ids:
            c = self.by_id.get(cid)
            if c is None or c.metadata.get("doc_type") != "statute":
                continue
            for user in self.users.get((c.doc_id, c.metadata.get("article")), []):
                for x in self.articles.get((c.doc_id, user), []):
                    if x not in have and x not in out:
                        out.append(x)
            if len(out) >= max_total:
                break
        return out[:max_total]

    def item_pieces(self, cid: str) -> list[str]:
        """판결요지 조각(CASE#…#n~k)이면 같은 항목의 모든 조각 ids, 아니면 [cid]."""
        m = CASE_ITEM.match(cid)
        if not m or m.group(3) is None:
            return [cid]
        return self.pieces.get(m.group(1) + m.group(2)) or [cid]

    def item_text(self, cid: str) -> str:
        """2-5 조각을 합친 판결요지 항목 전체 (머리줄 하나 + 본문들). 조각이 아니면 그 청크 본문."""
        ids = self.item_pieces(cid)
        if len(ids) == 1:
            return self.by_id[ids[0]].text
        head = re.sub(r"\s*\(\d+/\d+\)\s*$", "", self.by_id[ids[0]].text.split("\n", 1)[0])
        return head + "\n" + "\n".join(_body(self.by_id[x]) for x in ids if x in self.by_id)
