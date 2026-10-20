"""共享测试夹具：构建内存中的迷你索引."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kgrag.index.store import IndexStore  # noqa: E402
from kgrag.schemas import EvidenceRow  # noqa: E402
from kgrag.textproc import tokenize  # noqa: E402


def make_store(rows_spec: list[tuple[str, str, str, str]]) -> IndexStore:
    """rows_spec: (evidence_id, doc_id, line_no, text) -> IndexStore."""
    rows = []
    df: dict[str, int] = {}
    inv: dict[str, list[int]] = {}
    doc_rows: dict[str, list[int]] = {}
    for i, (eid, doc, line, text) in enumerate(rows_spec):
        toks = tokenize(f"{text} {text}")  # 重复一次拉高词频
        rows.append(EvidenceRow(
            evidence_id=eid, doc_id=doc, line_no=line, text=text,
            title=f"Title-{doc}", path="", entities=[], values=[], predicates=[],
            tokens=toks, dl=len(toks)))
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
            inv.setdefault(t, []).append(i)
        doc_rows.setdefault(doc, []).append(i)
    return IndexStore({"version": 2, "rows": [r.__dict__ for r in rows], "df": df,
                       "inv": inv, "N": len(rows),
                       "avgdl": (sum(r.dl for r in rows) / len(rows)) if rows else 1,
                       "doc_rows": doc_rows, "source_kg": "test"})


@pytest.fixture
def store() -> IndexStore:
    """迷你电镀语料（3 文档 6 证据行）."""
    return make_store([
        ("ev_aaa", "doc_1", 1, "PVP 抑制剂在钴电沉积中抑制钴还原"),
        ("ev_bbb", "doc_1", 2, "PVP 的酰胺基团吸附在电极表面"),
        ("ev_ccc", "doc_2", 1, "MPS 加速剂加速铜微孔填充过程"),
        ("ev_ddd", "doc_2", 2, "JGB 整平剂改善通孔填充均匀性"),
        ("ev_eee", "doc_3", 1, "糖精钠浓度 1 g/L 时镀层光亮"),
        ("ev_fff", "doc_3", 2, "电流密度 2 A/dm2 下电沉积铜"),
    ])
