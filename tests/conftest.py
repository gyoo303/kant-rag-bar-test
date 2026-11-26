import os
import tempfile
from pathlib import Path

import pytest
import yaml

from kant_rag.config import ROOT


def _neutral_config() -> str:
    """verify-2022 브랜치: configs/default.yaml 의 2022 검증 설정(기준일·별도 색인)을 단위 테스트에서는 끈다.
    테스트는 기준일이 없는 기본 동작을 검사하므로, 같은 설정에서 그 값만 되돌린 임시 파일을 쓴다."""
    data = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    data["paths"]["index_dir"] = "index"
    data["corpus"]["case_date_to"] = "20251231"
    data.get("retrieval", {}).pop("case_date_to", None)
    for k in ("asof_default", "hide_future"):
        data.get("mcq", {}).pop(k, None)
    f = Path(tempfile.mkdtemp()) / "test_config.yaml"
    f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(f)


os.environ["KANT_RAG_CONFIG"] = _neutral_config()

from kant_rag.config import get_settings  # noqa: E402

get_settings.cache_clear()
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
