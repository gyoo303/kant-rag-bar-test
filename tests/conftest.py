import pytest

from kant_rag.config import get_settings
from kant_rag.schemas import Chunk, DocumentMeta, RetrievedChunk


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def meta():
    return DocumentMeta(doc_id="D1", title="테스트", source="t", license="t", version="v1",
                        collected_at="2026-01-01", path="x.md")


def make_rc(cid: str, rank: int, source="vector", score=1.0) -> RetrievedChunk:
    c = Chunk(chunk_id=cid, doc_id=cid.split("#")[0], title="t", text=f"text {cid}")
    return RetrievedChunk(chunk=c, score=score, rank=rank, source=source, trace={f"{source}_rank": rank})
