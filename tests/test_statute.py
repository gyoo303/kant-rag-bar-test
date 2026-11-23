from kant_rag.ingest.statute import chunk_statute
from kant_rag.schemas import DocumentMeta

META = DocumentMeta(doc_id="LAW", title="민법", source="t", license="t", version="v", path="x", doc_type="statute")
TEXT = """제3편 채권
제5장 불법행위
제750조(불법행위의 내용) 고의 또는 과실로 인한 위법행위로 타인에게 손해를 가한 자는 그 손해를 배상할 책임이 있다.
제766조(손해배상청구권의 소멸시효) ① 첫째 항 내용입니다.
② 둘째 항 내용입니다.
제766조의2(가상 조문) 가지 조문 내용."""


def test_article_ids_and_sections():
    chunks = chunk_statute(TEXT, META, chunk_size=1200)
    assert [c.chunk_id for c in chunks] == ["LAW#제750조", "LAW#제766조", "LAW#제766조의2"]
    assert chunks[1].section == "제3편 채권 > 제5장 불법행위 > 제766조(손해배상청구권의 소멸시효)"
    assert (chunks[1].line_start, chunks[1].line_end) == (4, 5)
    assert "② 둘째 항" in chunks[1].text


def test_long_article_split_on_paragraph():
    chunks = chunk_statute(TEXT, META, chunk_size=20)
    ids = [c.chunk_id for c in chunks]
    assert "LAW#제766조-1" in ids and "LAW#제766조-2" in ids
