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


def prec_to_chunks(prec: dict, fetched_at: str | None = None) -> list[Chunk]:
    """판례 본문 JSON(PrecService) 하나를 필드 단위 청크로."""
    doc_id = str(prec.get("판례정보일련번호") or "").strip()
    if not doc_id:
        return []
    case_no = clean_text(prec.get("사건번호"))
    case_name = clean_text(prec.get("사건명"))
    base_meta = {
        "doc_id": doc_id,
        "doc_type": "prec",
        "case_no": case_no,
        "case_name": case_name,
        "court": clean_text(prec.get("법원명")),
        "decision_date": _fmt_date(prec.get("선고일자")),
        "judgment_type": clean_text(prec.get("판결유형")),
        "source": SOURCE_NAME,
        "fetched_at": fetched_at or "",
    }
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
