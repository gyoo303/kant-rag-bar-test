"""판례·조문 → 청크.

청크 ID 규칙 (docs/data_sources.md):
- 판례: "{판례일련번호}:{필드}:{순번}"   예) 625343:판결요지:0
- 조문: "law:{법령명}:{조번호}"         예) law:민법:750, law:민법:750-2
청크 본문 앞에 "[사건번호 사건명 | 필드]" 머리말을 붙여 검색 시 어느 판례의 어느 부분인지 드러나게 한다.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from civil_rag import config

SOURCE_NAME = "법제처 국가법령정보센터"

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SPACES = re.compile(r"[ \t　\xa0]+")
_BLANKS = re.compile(r"\n{3,}")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str            # "prec" | "law"
    section: str             # 원문 위치: 판례 필드명 또는 "제750조"
    text: str                # 머리말 포함 검색 대상 본문
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def clean_text(raw: str | None) -> str:
    """API 본문의 <br/> 등 HTML 태그·엔티티 제거, 공백 정리."""
    if not raw:
        return ""
    text = _BR.sub("\n", str(raw))
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


def _splitter() -> RecursiveCharacterTextSplitter:
    # 교안 2-2/2-3: RecursiveCharacterTextSplitter. 판례 문단 경계([1], 【이 유】)를 우선 분리점으로 둔다.
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", " [", "【", ". ", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def _fmt_date(yyyymmdd: str | None) -> str:
    s = (yyyymmdd or "").replace(".", "")
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}" if len(s) == 8 and s.isdigit() else (yyyymmdd or "")


# ── 참조조문·참조판례 → 메타데이터 ─────────────────────
_ARTICLE = re.compile(
    r"(?:(구\s*)?([가-힣·]+?(?:법률|법|령|규칙))\s*(?:\([^)]*\))?\s*)?제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
)
_SAME_LAW = {"동법", "같은법", "동"}
_CASE_NO = re.compile(r"\b(\d{2,4}\s*[가-힣]{1,3}\s*\d{1,6})\b")


def parse_ref_articles(text: str | None) -> list[str]:
    """'민법 제750조, 제751조 / 민사소송법 제208조' → ['law:민법:750', 'law:민법:751', 'law:민사소송법:208'].
    법령명이 생략되면 바로 앞 법령명을 이어 쓴다. 조문 청크 ID(law:법령명:조번호[-가지번호])와 같은 형식."""
    out: list[str] = []
    law = None
    for m in _ARTICLE.finditer(text or ""):
        name = m.group(2)
        if name and name not in _SAME_LAW:
            law = name
        if not law:
            continue
        key = f"law:{law}:{m.group(3)}" + (f"-{m.group(4)}" if m.group(4) else "")
        if key not in out:
            out.append(key)
    return out


def parse_ref_cases(text: str | None) -> list[str]:
    """참조판례의 사건번호 목록 (예: '99다24218')."""
    out = []
    for m in _CASE_NO.finditer(text or ""):
        no = re.sub(r"\s+", "", m.group(1))
        if no not in out:
            out.append(no)
    return out


def article_label(key: str) -> str:
    """'law:민법:750-2' → '민법 제750조의2'."""
    _, law, num = key.split(":", 2)
    base, _, branch = num.partition("-")
    return f"{law} 제{base}조" + (f"의{branch}" if branch else "")


# ── 판결요지 항목 나누기 ([1] [2] … 또는 가. 나. …) ───────
_HANGUL_SEQ = "가나다라마바사아자차카타파하"


def split_items(text: str) -> list[tuple[str, str]]:
    """원문 구조의 항목 표시를 순서대로만 인정해서 나눈다. 반환: [(표시, 본문)]. 표시가 없으면 [('', 전문)]."""
    text = text.strip()
    if not text:
        return []
    for kind in ("num", "hangul"):
        marks = []
        pos = 0
        for i in range(20):
            if kind == "num":
                label, pat = f"[{i + 1}]", re.compile(rf"(?:^|(?<=\s)|(?<=/))\[{i + 1}\]")
            else:
                if i >= len(_HANGUL_SEQ):
                    break
                ch = _HANGUL_SEQ[i]
                label, pat = f"{ch}.", re.compile(rf"(?:^|(?<=\s)|(?<=/)|(?<=\.)){ch}\.(?=\s|[가-힣])")
            m = pat.search(text, pos)
            if not m:
                break
            marks.append((label, m.start(), m.end()))
            pos = m.end()
        if len(marks) >= 2 and marks[0][1] <= 3:
            items = []
            for j, (label, _s, e) in enumerate(marks):
                end = marks[j + 1][1] if j + 1 < len(marks) else len(text)
                body = text[e:end].strip().rstrip("/").strip()
                if body:
                    items.append((label, body))
            return items
    return [("", text)]


def _prec_base_meta(prec: dict, fetched_at: str | None) -> dict:
    refs = parse_ref_articles(clean_text(prec.get("참조조문")))
    return {
        "doc_id": str(prec.get("판례정보일련번호") or "").strip(),
        "doc_type": "prec",
        "case_no": clean_text(prec.get("사건번호")),
        "case_name": clean_text(prec.get("사건명")),
        "court": clean_text(prec.get("법원명")),
        "decision_date": _fmt_date(prec.get("선고일자")),
        "judgment_type": clean_text(prec.get("판결유형")),
        "ref_articles": refs,
        "ref_articles_str": "|" + "|".join(refs) + "|" if refs else "",   # PGVector $like 필터용
        "ref_cases": parse_ref_cases(clean_text(prec.get("참조판례"))),
        "source": SOURCE_NAME,
        "fetched_at": fetched_at or "",
    }


def prec_to_chunks(prec: dict, fetched_at: str | None = None, strategy: str | None = None) -> list[Chunk]:
    """판례 본문 JSON(PrecService) 하나 → 청크. strategy 생략 시 config.CHUNK_STRATEGY."""
    strategy = strategy or config.CHUNK_STRATEGY
    if strategy == "field":
        return prec_to_chunks_field(prec, fetched_at)
    if strategy == "split":
        return prec_to_chunks_split(prec, fetched_at)
    raise ValueError(f"알 수 없는 CHUNK_STRATEGY: {strategy}")


def prec_to_chunks_field(prec: dict, fetched_at: str | None = None) -> list[Chunk]:
    """팀 결정 방식: 판시사항·판결요지를 원래 항목 단위로 한 조각씩. 글자 수로 자르지 않는다.
    참조조문은 메타데이터(ref_articles)로 두고, 검색에 도움이 되도록 조각 끝에 조문명 한 줄을 붙인다."""
    base = _prec_base_meta(prec, fetched_at)
    doc_id = base["doc_id"]
    if not doc_id:
        return []
    refs_line = ", ".join(article_label(k) for k in base["ref_articles"])
    chunks: list[Chunk] = []
    for section in config.FIELD_SECTIONS:
        for i, (label, body) in enumerate(split_items(clean_text(prec.get(section)))):
            cid = f"{doc_id}:{section}:{i}"
            header = f"[{base['case_no']} {base['case_name']} | {section}{' ' + label if label else ''}]"
            text = f"{header}\n{body}" + (f"\n참조조문: {refs_line}" if refs_line else "")
            meta = {**base, "chunk_id": cid, "section": section, "item": label, "part": i}
            chunks.append(Chunk(cid, doc_id, "prec", section, text, meta))
    if not chunks and config.FIELD_FULLTEXT_FALLBACK:
        return prec_to_chunks_split({k: v for k, v in prec.items() if k in ("판례정보일련번호", "사건번호", "사건명",
                                     "법원명", "선고일자", "판결유형", "참조조문", "참조판례", "판례내용")}, fetched_at)
    return chunks


def prec_to_chunks_split(prec: dict, fetched_at: str | None = None) -> list[Chunk]:
    """교안 2장 방식(비교용): 모든 필드(전문 포함)를 RecursiveCharacterTextSplitter 로 500자 분할."""
    base_meta = _prec_base_meta(prec, fetched_at)
    doc_id = base_meta["doc_id"]
    if not doc_id:
        return []
    case_no, case_name = base_meta["case_no"], base_meta["case_name"]
    splitter = _splitter()
    chunks: list[Chunk] = []
    for section in config.PREC_SECTIONS:
        body = clean_text(prec.get(section))
        if not body:
            continue
        header = f"[{case_no} {case_name} | {section}]"
        pieces = splitter.split_text(body) if len(body) > config.CHUNK_SIZE else [body]
        for i, piece in enumerate(pieces):
            cid = f"{doc_id}:{section}:{i}"
            meta = {**base_meta, "chunk_id": cid, "section": section, "part": i, "parts": len(pieces)}
            chunks.append(Chunk(cid, doc_id, "prec", section, f"{header}\n{piece}", meta))
    return chunks


def _flatten(node) -> list[str]:
    """조문의 항·호·목을 순서대로 펼친다 (dict 또는 list 모두 처리)."""
    out: list[str] = []
    if isinstance(node, list):
        for x in node:
            out.extend(_flatten(x))
    elif isinstance(node, dict):
        for key in ("항내용", "호내용", "목내용"):
            if node.get(key):
                val = node[key]
                out.extend(clean_text(v) for v in (val if isinstance(val, list) else [val]))
        for key in ("호", "목"):
            if key in node:
                out.extend(_flatten(node[key]))
    return [s for s in out if s]


def law_to_chunks(law_json: dict, fetched_at: str | None = None) -> list[Chunk]:
    """법령 본문 JSON(lawService target=law) → 조문 1개 = 청크 1개."""
    law = law_json.get("법령", law_json)
    info = law.get("기본정보", {})
    name = clean_text(info.get("법령명_한글"))
    units = law.get("조문", {}).get("조문단위", [])
    if isinstance(units, dict):
        units = [units]
    chunks: list[Chunk] = []
    for u in units:
        if u.get("조문여부") != "조문":   # "전문"은 편·장·절 제목
            continue
        num = str(u.get("조문번호", "")).strip()
        branch = str(u.get("조문가지번호", "") or "").strip()
        article = f"{num}-{branch}" if branch else num
        label = f"제{num}조" + (f"의{branch}" if branch else "")
        body = "\n".join([clean_text(u.get("조문내용"))] + _flatten(u.get("항", [])))
        if not body.strip():
            continue
        cid = f"law:{name}:{article}"
        meta = {
            "ref_articles": [cid],
            "ref_articles_str": f"|{cid}|",
            "chunk_id": cid,
            "doc_id": f"law:{name}",
            "doc_type": "law",
            "law_name": name,
            "article": label,
            "article_title": clean_text(u.get("조문제목")),
            "section": label,
            "effective_date": _fmt_date(info.get("시행일자")),
            "source": SOURCE_NAME,
            "fetched_at": fetched_at or "",
        }
        chunks.append(Chunk(cid, f"law:{name}", "law", label, f"[{name} {label}]\n{body}", meta))
    return chunks
