"""textproc 分词测试."""

from kgrag.textproc import latin_terms, query_terms, zh_terms


def test_basic_tokenize():
    toks = query_terms("PVP 在钴电沉积中起什么作用？")
    assert "pvp" in toks
    assert "钴" in toks or "电沉积" in " ".join(toks)
    # 停用词被剔除
    assert "什么" not in toks
    assert "作用" not in toks  # 模板词


def test_english_and_numbers():
    toks = query_terms("What is CuSO4 concentration 2.5 g/L?")
    assert "cuso4" in toks
    assert "2.5" in toks
    assert "what" not in toks


def test_latin_terms():
    assert latin_terms("PVP 与 MPS", min_len=2) == ["pvp", "mps"]
    assert latin_terms("a b", min_len=2) == []


def test_zh_terms():
    assert zh_terms("聚乙烯吡咯烷酮") == ["聚乙烯吡咯烷酮"]


def test_empty_and_none():
    assert query_terms("") == []
    assert latin_terms(None) == []
