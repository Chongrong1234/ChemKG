"""提示词模板与证据摘录式兜底回答."""

from __future__ import annotations

from kgrag.schemas import RetrievalHit

SYSTEM_PROMPT = (
    "你是电镀领域的科研文献问答助手。必须遵守：\n"
    "1. 只根据给定证据回答问题；证据不足以推出结论时，明确说明“现有证据不足”；\n"
    "2. 保留证据中的关键实验条件（温度、电流密度、浓度、基底等数值与单位）；\n"
    "3. 每个主要结论后在句末标注引用，格式如 [ev_xxxx]（本地文献）或 [web_xxxx]（联网期刊文献）；\n"
    "4. 若不同文献证据相互冲突，如实并列说明而不是强行取舍；"
    "联网检索到的期刊摘要（标注“联网文献”）与本地知识库证据同等对待，"
    "结论更倾向有具体实验数据支撑的证据；\n"
    "5. 使用中文回答，专业术语首次出现时可附英文缩写。"
)


def format_context(hits: list[RetrievalHit]) -> str:
    """将命中证据编排为带编号的上下文块（本地 / 联网文献分来源标注）."""
    blocks = []
    for i, h in enumerate(hits, 1):
        if h.row.source == "web":
            meta = f"联网文献：{h.row.journal}"
            if h.row.year:
                meta += f" ({h.row.year})"
            if h.row.authors:
                meta += f"，{h.row.authors[0]} et al."
            if h.row.doi:
                meta += f"，DOI: {h.row.doi}"
            lines = [f"[{i}] {h.row.text}（{meta}，标题：{h.row.title}，evidence_id={h.row.evidence_id}）"]
        else:
            lines = [f"[{i}] {h.row.text}（来源：{h.row.title}，evidence_id={h.row.evidence_id}）"]
        for n in h.neighbors:
            lines.append(f"    上下文(L{n.line_no})：{n.text}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_answer_messages(question: str, hits: list[RetrievalHit],
                          history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """构造 chat messages（可选携带最近几轮问答历史以支持追问）."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-3:]:  # 最近 3 轮，防止上下文过长
        if turn.get("question"):
            messages.append({"role": "user", "content": turn["question"]})
        if turn.get("answer"):
            messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({
        "role": "user",
        "content": f"问题：{question}\n\n证据：\n{format_context(hits)}" if hits
        else f"问题：{question}\n\n（知识库未检索到相关证据，请如实告知证据不足）",
    })
    return messages


def extractive_answer(hits: list[RetrievalHit]) -> str:
    """LLM 不可用/失败时的证据摘录式回答（可回溯、可审计）."""
    if not hits:
        return "当前知识库没有检索到足够的证据，暂不作答。"
    lines = ["基于当前知识库检索到的证据，相关信息如下："]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.row.text}（{h.row.title}，evidence_id={h.row.evidence_id}）")
    lines.append("\n说明：以上为证据摘录；候选事实尚未自动等同于已验证科学结论，请结合实验条件和原文核对。")
    return "\n".join(lines)
