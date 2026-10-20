"""联网学术文献检索（OpenAlex）.

特性：
- 目标期刊白名单（ISSN 过滤）：Journal of Electroanalytical Chemistry、
  Electrochimica Acta、ACS Omega、Colloids & Surfaces A、Chemical Engineering
  Journal、Small、ACS AMI、J. Mater. Chem. A/C、Applied Surface Science、
  Journal of Alloys and Compounds；
- LLM 将中文问题转写为英文检索式（失败时回退到问题中的拉丁词）；
- 检索结果转换为 ``RetrievalHit``（伪 ``EvidenceRow``），无缝融入既有
  证据编排 / 提示词 / 前端渲染管线；
- 网络失败静默降级为空结果，绝不中断问答主流程。
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

import httpx

from kgrag.generation.llm import LLMClient
from kgrag.schemas import EvidenceRow, NeighborLine, RetrievalHit

logger = logging.getLogger("kgrag.websearch")

OPENALEX_URL = "https://api.openalex.org/works"
MAILTO = "kgrag-search@example.com"

# ---------------------------------------------------------------------------
# 目标期刊白名单（ISSN，print|online 均收录）
# ---------------------------------------------------------------------------
TARGET_JOURNALS: dict[str, list[str]] = {
    "Journal of Electroanalytical Chemistry": ["0022-0728", "1572-6657"],
    "Electrochimica Acta": ["0013-4686"],
    "ACS Omega": ["2470-1343"],
    "Colloids and Surfaces A": ["0927-7757"],
    "Chemical Engineering Journal": ["1385-8947"],
    "Small": ["1613-6810", "1613-6829"],
    "ACS Applied Materials & Interfaces": ["1944-8244", "1944-8252"],
    "Journal of Materials Chemistry A": ["2050-7488", "2050-7496"],
    "Journal of Materials Chemistry C": ["2050-7526", "2050-7515"],
    "Applied Surface Science": ["0169-4332"],
    "Journal of Alloys and Compounds": ["0925-8388"],
}
_TARGET_ISSN_FILTER = "|".join(i for issns in TARGET_JOURNALS.values() for i in issns)

# OpenAlex select 字段（减小响应体积）
_SELECT = ",".join([
    "id", "doi", "title", "publication_year", "authorships",
    "abstract_inverted_index", "primary_location", "relevance_score",
])

QUERY_SYSTEM_PROMPT = (
    "You are a search-query generator for electrochemistry / electroplating "
    "literature databases (OpenAlex). Rewrite the user's question as ONE concise "
    "English keyword query for full-text academic search. Rules:\n"
    "- Expand acronyms: e.g. PVP -> 'polyvinylpyrrolidone PVP', JGB -> 'JGB leveler'\n"
    "- Include the core chemical system and technique words (e.g. 'cobalt "
    "electrodeposition', 'copper electroplating', 'additive inhibitor')\n"
    "- Drop filler words like 'role', 'effect', 'mechanism of', 'what is'\n"
    "- Max ~12 words, space-separated. Output ONLY the query itself — no quotes, "
    "no explanation, no trailing period."
)


# ---------------------------------------------------------------------------
@dataclass
class _CacheEntry:
    results: list[RetrievalHit]
    ts: float


@dataclass
class WebSearchClient:
    """OpenAlex 检索客户端（带 TTL 内存缓存）."""

    timeout_s: float = 20.0
    abstract_max_chars: int = 900
    _cache: dict[str, _CacheEntry] = field(default_factory=dict, repr=False)
    _cache_ttl_s: float = 600.0

    # ------------------------------------------------------------------
    def build_query(self, question: str, llm: LLMClient | None = None) -> str:
        """中文问题 -> 英文检索式（LLM 转写，失败回退拉丁词）."""
        if llm is not None:
            try:
                result = llm.chat(
                    [{"role": "system", "content": QUERY_SYSTEM_PROMPT},
                     {"role": "user", "content": question}],
                    thinking=False, max_tokens=80,
                )
                query = " ".join(result.content.strip().split())
                # 简单合理性检查：非空、不过长、不含换行解释
                if result.ok and 4 <= len(query) <= 160 and "\n" not in query:
                    return query
                logger.info("LLM 检索式不合理，回退：%r", query[:80])
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 检索式生成失败：%s", exc)
        return self._fallback_query(question)

    @staticmethod
    def _fallback_query(question: str) -> str:
        """回退：抽取问题中的拉丁词/缩写，补上领域词."""
        from kgrag.textproc import latin_terms
        terms = [t for t in latin_terms(question) if len(t) >= 2]
        if not terms:
            terms = [question.strip()[:60]]
        return " ".join(dict.fromkeys(terms + ["electrochemistry"]))

    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 12) -> list[RetrievalHit]:
        """检索目标期刊文献，返回伪 ``RetrievalHit`` 列表（网络失败返回 []）."""
        query = (query or "").strip()
        if not query or limit <= 0:
            return []
        cached = self._cache.get(query)
        if cached and time.monotonic() - cached.ts < self._cache_ttl_s:
            return cached.results[:limit]

        try:
            params = {
                "search": query,
                "filter": f"primary_location.source.issn:{_TARGET_ISSN_FILTER},has_abstract:true",
                "per-page": str(max(limit, 25)),
                "select": _SELECT,
                "mailto": MAILTO,
            }
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
                resp = client.get(OPENALEX_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 联网失败静默降级
            logger.warning("OpenAlex 检索失败：%s", exc)
            return []

        hits: list[RetrievalHit] = []
        seen_dois: set[str] = set()
        for work in data.get("results", []):
            abstract = _rebuild_abstract(work.get("abstract_inverted_index"))
            if not abstract:
                continue
            doi = (work.get("doi") or "").replace("https://doi.org/", "").strip()
            if doi and doi in seen_dois:
                continue
            if doi:
                seen_dois.add(doi)
            source = (work.get("primary_location") or {}).get("source") or {}
            journal = source.get("display_name") or "未知期刊"
            if journal not in TARGET_JOURNALS and not _journal_match(journal):
                continue  # 白名单兜底
            title = (work.get("title") or "").strip()
            abstract = abstract[: self.abstract_max_chars].rsplit(" ", 1)[0] if len(abstract) > self.abstract_max_chars else abstract
            authors = [a.get("author", {}).get("display_name", "")
                       for a in (work.get("authorships") or []) if a.get("author", {}).get("display_name")]
            eid = "web_" + hashlib.sha1(
                (doi or title).encode("utf-8")).hexdigest()[:8]
            row = EvidenceRow(
                evidence_id=eid, doc_id="web", line_no=0,
                text=abstract, title=title, path=f"https://doi.org/{doi}" if doi else "",
                source="web", journal=journal,
                year=work.get("publication_year"), authors=authors[:6], doi=doi,
            )
            hits.append(RetrievalHit(row=row, score=0.0, matched_terms=[]))
        # 排名即相关性顺序；分数按排名赋降序（仅用于展示与排序，不参与 BM25 语义）
        for i, h in enumerate(hits):
            h.score = round(max(0.9 - 0.05 * i, 0.1), 4)

        self._cache[query] = _CacheEntry(results=hits, ts=time.monotonic())
        return hits[:limit]


# ---------------------------------------------------------------------------
def _journal_match(journal: str) -> bool:
    """宽松匹配：OpenAlex 期刊名与白名单（处理子串/大小写差异）."""
    j = journal.lower()
    return any(name.lower() in j or j in name.lower() for name in TARGET_JOURNALS)


def _rebuild_abstract(inverted: dict | None) -> str:
    """从 OpenAlex 倒排索引重建摘要文本."""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort()
    return " ".join(w for _, w in positions)
