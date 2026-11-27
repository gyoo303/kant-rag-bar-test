from conftest import make_rc

from kant_rag.retrieval.hybrid import rrf_fuse
from kant_rag.retrieval.tokenizer import simple_tokenize


def test_rrf_dedup_and_order():
    vec = [make_rc("D1#a", 1), make_rc("D1#b", 2), make_rc("D1#c", 3)]
    bm = [make_rc("D1#b", 1, "bm25"), make_rc("D1#d", 2, "bm25")]
    fused = rrf_fuse({"vector": vec, "bm25": bm}, rrf_k=60, top_k=10)
    ids = [r.chunk.chunk_id for r in fused]
    assert ids[0] == "D1#b"  # 양쪽 모두 등장 → 최상위
    assert len(ids) == len(set(ids)) == 4
    top = fused[0].trace
    assert top["vector_rank"] == 2 and top["bm25_rank"] == 1 and top["rrf_rank"] == 1
    assert abs(fused[0].score - (1 / 62 + 1 / 61)) < 1e-12


def test_simple_tokenizer_korean_bigrams():
    toks = simple_tokenize("개봉상품은 반품 불가, Error 404")
    assert "개봉상품은" in toks and "개봉" in toks and "error" in toks and "404" in toks
