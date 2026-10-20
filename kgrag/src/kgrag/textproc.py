"""中英混合分词与停用词处理.

设计要点：
- 英文/数字使用正则切词，中文优先使用 jieba，缺失时退化为二元切分；
- 停用词表剔除中英文的通用虚词与问答模板词，保留领域判别性词
  （化学名、添加剂、工艺条件），避免模板文本主导 BM25 打分。
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+./-]*|[\u4e00-\u9fff]+|\d+(?:\.\d+)?")
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./-]*")
ZH_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

STOP = frozenset(
    "the and for with from that this are was were has have into using used under through "
    "about which their there then than can may not does how what why where when whose".split()
)

ZH_STOP = frozenset(
    """的 了 是 在 和 与 对 于 及 其 中 以 由 将 被 也 都 还 有 这 那 个 一 不 可 能 等 作为
    什么 如何 是否 没有 哪些 哪 有没有 内容 报道 文献 知识库 记录 证据 线索 问题 作用
    时候 起来 进行 关于 研究 过程 能够 可以 具有 出现 表明 说明 结果 以及 因此 另外
    其中 这些 那些""".split()
)

try:  # jieba 可选：缺失时使用二元退化切分
    import jieba

    jieba.setLogLevel(60)  # 关闭 jieba 初始化日志噪音

    def _zh_words(run: str) -> list[str]:
        return [w.strip() for w in jieba.lcut(run) if w.strip()]

except Exception:  # pragma: no cover - 仅在无 jieba 环境触发
    def _zh_words(run: str) -> list[str]:
        return [run[i : i + 2] for i in range(len(run) - 1)] or ([run] if run else [])


def tokenize(text: str) -> list[str]:
    """将中英混合文本切分为小写词元列表（已剔除停用词）."""
    out: list[str] = []
    for tok in TOKEN_RE.findall((text or "").lower()):
        first = tok[:1]
        if "\u4e00" <= first <= "\u9fff":
            out.extend(w for w in _zh_words(tok) if w not in ZH_STOP)
        elif len(tok) > 1 and tok not in STOP:
            out.append(tok)
    return out


def latin_terms(text: str, min_len: int = 1) -> list[str]:
    """提取拉丁字母词元（小写），用于实体锚定匹配."""
    return [t.lower() for t in LATIN_RE.findall(text or "") if len(t) >= min_len]


def zh_terms(text: str, min_len: int = 2, max_len: int = 12) -> list[str]:
    """提取连续中文串，用于实体锚定匹配（化学物质中文名可达 10+ 字）."""
    return [t for t in ZH_RUN_RE.findall(text or "") if min_len <= len(t) <= max_len]


def query_terms(question: str) -> list[str]:
    """问题分词（与文档侧一致的口径）."""
    return tokenize(question)
