from kant_rag.ingest.split import split_long
from kant_rag.schemas import Chunk


def test_short_chunk_untouched():
    c = Chunk(chunk_id="LAW#제1조", doc_id="LAW", title="t", text="[민법] 제1조\n짧은 본문")
    assert split_long(c, 1000) == [c]


def test_long_chunk_split_with_header_and_ids():
    body = " ".join(f"문장 {i} 은 길게 이어지는 판결요지의 일부이다." for i in range(200))
    c = Chunk(chunk_id="CASE#2019다1#1", doc_id="CASES", title="t", text="[판례] 대법원 2019다1 판결요지 [1]\n" + body)
    parts = split_long(c, 400)
    assert len(parts) > 1 and all(len(p.text) <= 400 for p in parts)
    assert [p.chunk_id for p in parts][:2] == ["CASE#2019다1#1~1", "CASE#2019다1#1~2"]
    assert all(p.text.startswith("[판례] 대법원 2019다1 판결요지 [1] (") for p in parts)
    joined = "".join(p.text.split("\n", 1)[1] for p in parts)
    assert joined.replace(" ", "").replace("\n", "") == body.replace(" ", "")
