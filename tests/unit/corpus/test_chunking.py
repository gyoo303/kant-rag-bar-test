"""TKT-BE-M2-01: 청킹 규칙 (03-db-schema §4, INV-02)."""

from __future__ import annotations

from typing import Any

import pytest

from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.domain.models import SourceDocument
from lawqa.corpus.infrastructure.kiwi_tokenizer import KiwiTokenizer

IDX = "idx-aaaaaaaa-bbbbbbbb"
POLICY = ChunkingPolicy(max_chars=1500, overlap_chars=150)


def split_words(text: str) -> list[str]:
    return text.split()


def _prec(**changes: Any) -> SourceDocument:
    data: dict[str, Any] = {
        "판례정보일련번호": "112855",
        "사건명": "해고무효확인",
        "사건번호": "94다43351",
        "선고일자": "19951205",
        "법원명": "대법원",
        "사건종류명": "민사",
        "판시사항": "  [1] 첫째 판시 <br/>  [2] [1]항의 처분이 정당한 경우<br/>",
        "판결요지": "  [1] 첫째 요지.<br/>  [2] 둘째 요지.<br/>",
        "참조조문": "[1]근로기준법 제27조 제1항<br/>",
    }
    data.update(changes)
    return SourceDocument.from_prec_service(data, "prec/112855.json")


def _article(body: str, no: int = 103, title: str = "반사회질서의 법률행위") -> SourceDocument:
    text = f"제{no}조({title})\n{body}\n"
    docs, _ = SourceDocument.statute_articles_from_text(text, "statutes/민법.txt", "민법")
    return docs[0]


def test_precedent_items_grouped_by_number_with_location_and_references() -> None:
    chunks = POLICY.split(_prec(), IDX, split_words)

    assert [c.chunk_id for c in chunks] == ["prec:112855#HOLDING#1", "prec:112855#HOLDING#2"]
    assert chunks[0].location.text == "대법원 1995. 12. 5. 선고 94다43351 판결 [1]"
    assert chunks[0].text.splitlines()[0] == (
        "대법원 1995. 12. 5. 선고 94다43351 판결 [1] | 참조조문: [1]근로기준법 제27조 제1항"
    )
    assert "[판시사항] 첫째 판시" in chunks[0].text and "[판결요지] 첫째 요지." in chunks[0].text
    assert chunks[0].bm25_tokens == tuple(chunks[0].text.split())
    assert all(c.section == "HOLDING" and c.index_version == IDX for c in chunks)


def test_inline_item_reference_is_not_a_split_point() -> None:
    chunks = POLICY.split(_prec(), IDX, split_words)

    assert "[판시사항] [1]항의 처분이 정당한 경우" in chunks[1].text
    assert len(chunks) == 2


def test_items_present_on_one_side_only_are_kept() -> None:
    doc = _prec(
        판시사항="[1] 가<br/>[2] 나<br/>[3] 다",
        판결요지="[1] 가 요지<br/>[2] 나 요지",
    )

    chunks = POLICY.split(doc, IDX, split_words)

    assert [c.location.text.rsplit(" ", 1)[-1] for c in chunks] == ["[1]", "[2]", "[3]"]
    assert "[판결요지]" not in chunks[2].text


def test_unmarked_side_makes_single_chunk() -> None:
    doc = _prec(판시사항="[1] 가<br/>[2] 나", 판결요지="번호 없는 요지 전체.")

    chunks = POLICY.split(doc, IDX, split_words)

    assert len(chunks) == 1
    assert chunks[0].location.text == "대법원 1995. 12. 5. 선고 94다43351 판결"


def test_long_precedent_split_at_sentences_with_overlap_and_limit() -> None:
    sentence = "이 문장은 판결요지의 긴 내용을 흉내 내는 시험 문장이다."
    doc = _prec(판시사항="", 판결요지=" ".join([sentence] * 60), 참조조문="")
    policy = ChunkingPolicy(max_chars=300, overlap_chars=40)

    chunks = policy.split(doc, IDX, split_words)

    assert len(chunks) > 1
    assert all(len(c.text) <= 300 for c in chunks)
    assert [c.seq for c in chunks] == list(range(1, len(chunks) + 1))
    first_body = chunks[0].text.splitlines()[1]
    second_body = chunks[1].text.splitlines()[1]
    assert second_body.startswith(first_body[-40:].strip()[:10])


def test_long_reference_is_capped_in_header_but_kept_in_field() -> None:
    references = "<br/>".join(f"민법 제{n}조" for n in range(1, 400))
    doc = _prec(참조조문=references)

    chunks = POLICY.split(doc, IDX, split_words)

    header = chunks[0].text.splitlines()[0]
    assert header.endswith("…") and len(header) < 400
    assert all(len(c.text) <= POLICY.max_chars for c in chunks)
    assert chunks[0].referenced_articles == doc.referenced_articles


def test_short_article_is_one_chunk_with_title_heading() -> None:
    doc = _article("①첫째 항이다.\n②둘째 항이다.")

    chunks = POLICY.split(doc, IDX, split_words)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "law:민법:103-0#ARTICLE#1"
    assert chunks[0].location.text == "민법 제103조"
    assert chunks[0].text == "민법 제103조(반사회질서의 법률행위)\n①첫째 항이다.\n②둘째 항이다."
    assert chunks[0].referenced_articles is None


def test_long_article_split_at_paragraphs_with_range_location() -> None:
    paragraphs = "\n".join(f"{chr(0x2460 + i)}{'가' * 90}" for i in range(5))
    policy = ChunkingPolicy(max_chars=250, overlap_chars=20)

    chunks = policy.split(_article(paragraphs), IDX, split_words)

    assert [c.location.text for c in chunks] == [
        "민법 제103조 제1항~제2항",
        "민법 제103조 제3항~제4항",
        "민법 제103조 제5항",
    ]
    assert all(len(c.text) <= 250 for c in chunks)
    assert chunks[1].text.startswith("민법 제103조 제3항~제4항(반사회질서의 법률행위)\n③")


def test_policy_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        ChunkingPolicy(max_chars=0, overlap_chars=0)
    with pytest.raises(ValueError):
        ChunkingPolicy(max_chars=100, overlap_chars=100)


def test_kiwi_tokenizer_keeps_content_morphemes() -> None:
    tokens = KiwiTokenizer()("임차인은 임대인에게 보증금의 반환을 청구할 수 있다.")

    assert "임차인" in tokens and "보증금" in tokens and "반환" in tokens
    assert "은" not in tokens and "에게" not in tokens
