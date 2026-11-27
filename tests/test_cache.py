from kant_rag.optimize.cache import AnswerCache, cache_key


def test_key_changes_with_version_and_scope(settings):
    k1 = cache_key("반품 조건은?", settings, "hybrid_rerank")
    assert k1 == cache_key("  반품   조건은 ", settings, "hybrid_rerank")  # 정규화
    assert k1 != cache_key("반품 조건은?", settings, "hybrid_rerank", user_scope="hr")
    s2 = settings.model_copy(deep=True)
    s2.versions.index = "index-v9"
    assert k1 != cache_key("반품 조건은?", s2, "hybrid_rerank")


def test_ttl_and_invalidate(tmp_path):
    c = AnswerCache(tmp_path / "c.sqlite", ttl_seconds=1000)
    c.set("k", {"a": 1})
    assert c.get("k") == {"a": 1}
    assert c.invalidate() == 1 and c.get("k") is None
    expired = AnswerCache(tmp_path / "c.sqlite", ttl_seconds=-1)
    expired.set("k", {"a": 1})
    assert expired.get("k") is None
