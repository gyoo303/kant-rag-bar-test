from kant_rag.ingest.chunker import chunk_text
from kant_rag.ingest.loader import clean_text

DOC = "# 제목\n\n## A절\n" + "\n".join(f"A 내용 {i} " * 5 for i in range(20)) + "\n\n## B절\nB 내용\n"


def test_ids_are_stable_and_unique(meta):
    a = chunk_text(clean_text(DOC), meta, 200, 40)
    b = chunk_text(clean_text(DOC), meta, 200, 40)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


def test_location_points_to_source_lines(meta):
    text = clean_text(DOC)
    lines = text.split("\n")
    for c in chunk_text(text, meta, 200, 40):
        assert c.line_start <= c.line_end
        body = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert body.strip() and body.split("\n")[-1] in c.text
        assert text[c.char_start : c.char_end] == body


def test_sections_and_overlap(meta):
    chunks = chunk_text(clean_text(DOC), meta, 200, 40)
    assert any(c.section and c.section.endswith("B절") for c in chunks)
    a_chunks = [c for c in chunks if c.section and c.section.endswith("A절")]
    assert len(a_chunks) > 1
    assert a_chunks[1].line_start <= a_chunks[0].line_end  # 겹침 존재
