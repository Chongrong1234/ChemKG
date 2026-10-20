# KG-RAG Gold 评测与实验报告

## 1. 背景与目标

KG 在本轮迭代后新增了严格抽取层（strict extraction）、GPT-5.6 模型判定 golden benchmark、QA 扩展层和多模型 jury 复核。本报告在此基础上：

1. 以模型判定 gold（gpt-5.6-terra 判定的 24 条严格候选关系）为真值构建 RAG gold 评测集；
2. 在该 gold 集上完成检索层与答案层的完整实验；
3. 用 4 个独立模型做 LLM-as-judge 交叉评分，并报告裁判间一致率；
4. 给出诚实结论：哪些结论可信、哪些受限于样本量与模型判定真值。

**重要限定**：本报告的 gold 真值来自 GPT-5.6 模型判定（`model_judged_not_human`），不是人工专家标注。所有数字适合作为内部回归与系统对比，不能作为论文中的科学准确率。

## 2. Gold 评测集构建

### 2.1 来源

```text
真值来源:   golden_benchmark/gold_test.jsonl（24 条，seed=2025 固定切分）
           19 条 supported（可回答）
           5 条 unsupported/contradicted（对抗探针：KG 声称的关系不被证据支持）
证据来源:   strict_extraction_verify/evidence.jsonl（1,290 条证据，46 篇文档）
索引:      rag_index_strict（与 gold 证据同源，24/24 gold evidence 全覆盖）
```

### 2.2 构建方式（rag_gold_builder.py）

- 每条 gold 事实生成一个自然语言问题（实体 + 关系导向，非模板堆砌，不含原文线索）；
- 可回答项：gold answer = 关系结论 + 关键实验条件（浓度/电位/转速/pH 等）；
- 对抗探针：问题仍按被否定的关系提问，gold answer = "不能支持该说法" + 判定理由；
- 问题措辞刻意避免 anchored silver 集的线索泄漏问题（不把原文片段放进问题）。

### 2.3 Gold 集统计

| 项 | 数值 |
|---|---:|
| 总问题 | 24 |
| 可回答 | 19 |
| 对抗探针（应为"不支持"） | 5 |
| 关系分布 | inhibits 12 / accelerates 6 / improves 4 / synergizes 2 |
| 平均 gold 证据长度 | 909 字符（长段落，含多句） |

## 3. 实验一：检索层（rag_gold_retrieval_eval.py）

索引：rag_index_strict（1,290 行证据）。指标：gold evidence 是否进入 top-k。

| 系统 | Hit@5 | MRR@5 | Hit@10 | MRR@10 | P50 延迟 |
|---|---:|---:|---:|---:|---:|
| lexical BM25 | 0.421 | 0.175 | 0.579 | 0.195 | 4.1 ms |
| KG-aware BM25 | 0.474 | 0.258 | 0.579 | 0.273 | 6.0 ms |
| **subject-anchored v3** | **0.632** | **0.394** | **0.789** | **0.418** | 6.4 ms |
| BGE dense（bge-small-zh-v1.5） | 0.053 | — | 0.053 | — | <1 ms* |
| RRF hybrid（BM25+dense） | 0.263 | — | 0.316 | — | ~13 ms |
| clause-level RRF hybrid | 0.316 | — | 0.421 | — | ~15 ms |

*dense 延迟不含一次性编码（约 60 s，可离线预计算）。

对抗探针证据（用于否定的证据）检索命中：lexical 2/5，KG-aware 3/5，v3 4/5。

### 3.1 本轮修复的两个关键缺陷

1. **拒答 guard 误伤**：旧 guard 用 3-8 字中文 n-gram 匹配语料 blob，问题套话（"它是抑制沉积吗"）触发误拒答，导致 17/19 问题直接返回空。修复为：仅当问题中的拉丁字母材料词全部未知且无已知词时才拒答。修复后 Hit@5 从 0.105 → 0.632。
2. **长段落稀释**：gold 证据是平均 909 字符的多句段落，BM25 把同实体其他实验的段落排更高。subject-anchored v3（证据含主语材料词 ×2.5 加权）把 Hit@5 从 0.474 → 0.632。

### 3.2 结论

- **词法 BM25 + 主体锚定（v3）是当前最优检索形态**；BGE dense 在该证据形态（长段落、实体缩写主导）下远差于词法（0.053 vs 0.632），与上一轮 silver 集结论一致。
- v3 的 anchor 信息来自 gold 集的 subject 字段——生产系统需要实体识别/链接先从问题中提取 subject，这是下一阶段的必要组件（KG 实体表可承担）。
- 对抗探针证据 4/5 可检索：系统有机会"看到"否定证据，答案层是否能利用是另一问题（见实验二）。

## 4. 实验二：答案层（rag_answer_eval.py + rag_judge.py）

### 4.1 设计

- 检索：v3 subject-anchored，top-5 证据；
- 生成系统：extractive（确定性摘录）+ 4 个 LLM（glm-5.3 / qwen3.7-max / deepseek-v4-pro-0813 / kimi-k2.6），统一系统提示（只用证据、保留条件、引用 [E1]、150 字内）；
- 评分：4 个 LLM 裁判对每个（系统回答， gold）打分：correctness / evidence_support / condition_retention（各 0-2 归一 0-1）、abstention（0/1，仅对抗项）；
- 共 480 次裁判调用，成功 445 次（92.7%）；失败集中在 glm/deepseek 裁判（推理 token 超预算，已通过提高 max_tokens 与 reasoning_content 回退修复大部分）。

### 4.2 结果（可回答项 19 条 × 4 裁判平均）

| 系统 | correctness | evidence_support | condition_retention | 对抗拒答率 |
|---|---:|---:|---:|---:|
| extractive | 0.993 | 1.000 | 0.797 | 0.267 |
| kimi-k2.6 | 0.979 | 0.937 | 0.648 | 0.722 |
| qwen3.7-max | 0.978 | 0.913 | 0.594 | 0.471 |
| glm-5.3 | 0.958 | 0.924 | 0.639 | 0.842 |
| deepseek-v4-pro-0813 | 0.910 | 0.896 | 0.639 | 0.667 |

裁判间一致率（correctness 完全一致）：0.83–0.96；±1 分一致率 ≥0.99。

分关系 correctness（4 裁判平均）：

| 系统 | inhibits | accelerates | improves | synergizes |
|---|---:|---:|---:|---:|
| extractive | 1.000 | 0.958 | 1.000 | 1.000 |
| kimi-k2.6 | 0.989 | 1.000 | 0.929 | 0.938 |
| qwen3.7-max | 0.978 | 1.000 | 0.917 | 1.000 |
| glm-5.3 | 0.978 | 0.958 | 1.000 | 0.857 |
| deepseek-v4-pro-0813 | 0.911 | 0.958 | 0.929 | 0.812 |

### 4.3 关键观察（含有效性警告）

1. **extractive 的 0.993 correctness 有度量成分**：它只摘录证据原文，裁判把"包含正确证据"视为正确回答。它真实反映的是"检索层能把对的证据送进来"，不是综合问答能力。其条件保留（0.797）高于所有 LLM（0.59-0.65）——摘录原文天然保留条件，LLM 综述时更易丢。
2. **LLM 的真正优势在对抗拒答**：glm 0.842 / kimi 0.722 / deepseek 0.667 vs extractive 0.267。extractive 面对不支持的声称仍罗列证据，不拒绝；LLM 能依据证据说"不支持该说法"。例如 PVP 加速钴沉积探针：4 个 LLM 全部正确回答"是抑制而非加速"。
3. **condition_retention 是所有 LLM 的弱项**（0.59-0.65 vs extractive 0.797）：LLM 综述时丢失浓度/电位/转速等条件的倾向明确，是下一版提示工程与评分重点。
4. **deepseek 的早期低分部分是基础设施问题**：3 条 glm 回答被截断为 1-2 字符（API 截断），重新生成后全部升到满分；deepseek 裁判因推理 token 超预算失败率高。模型对比结论应打折扣：glm/kimi/qwen 之间在 n=19 上无可信显著差异。
5. **qwen3.7-max 在 contradicted 探针上拒答失败**（MPS 改善填充：它回答"无明显改善，但能与 MG 协同"）：证据确实支持协同，但 gold 标签只否定单独改善——这是 gold 标签粒度 vs 问题粒度的边界案例，人工审核时应重新裁决。

## 5. 综合结论

1. **检索层**：subject-anchored BM25 v3 是当前最优（Hit@5 0.632 / Hit@10 0.789 / MRR 0.394），已集成进 rag_system.retrieve（subject_anchor + predicate_hint 参数）与 rag_api（/ask 支持 subject 与 predicate_hint）。BGE dense 在该形态下不占优，维持"词法优先"结论。
2. **答案层**：LLM 生成在可回答项上与 extractive 相当（0.91-0.98 vs 0.99），但在对抗拒答上大幅领先（0.47-0.84 vs 0.27）。生产建议：可回答项用 extractive 保条件，对抗/开放问题用 LLM 判定支持性；或 LLM + 强制条件保留提示。
3. **裁判可信度**：4 裁判 exact 一致率 0.83-0.96，within-1 一致率 ≥0.99，评分可信；但 n=19/5 的样本量不足以区分 LLM 之间差异。
4. **Gold 真值仍是模型判定**：上线/论文前必须人工复核 24 条（尤其 5 条对抗探针中 qwen 拒答失败的边界案例）。

## 6. 复现命令

```bash
# 1. 构建 gold QA 集（24 条）
python rag_gold_builder.py --gold golden_benchmark/gold_test.jsonl \
    --relations strict_extraction_verify/relations.jsonl \
    --entities strict_extraction_verify/entities.jsonl \
    --out evaluation/gold_qa.jsonl

# 2. 检索层评测
python rag_gold_retrieval_eval.py --index rag_index_strict \
    --gold evaluation/gold_qa.jsonl --out evaluation/gold_retrieval_metrics.json

# 3. 答案生成（需要 RAG_LLM_API_KEY）
RAG_LLM_API_KEY=... python rag_answer_eval.py --index rag_index_strict \
    --gold evaluation/gold_qa.jsonl \
    --models glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 \
    --out evaluation/answers.jsonl

# 4. LLM-as-judge（4 裁判 × 5 系统 × 24 题）
RAG_LLM_API_KEY=... python rag_judge.py --answers evaluation/answers.jsonl \
    --judges glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 \
    --out evaluation/judged.jsonl --workers 8

# 5. 汇总
python rag_judge_aggregate.py --judged evaluation/judged.jsonl \
    --out evaluation/gold_answer_metrics.json
```

## 7. 产出文件

| 文件 | 内容 |
|---|---|
| `rag_gold_builder.py` | gold QA 集构建 |
| `rag_gold_retrieval_eval.py` | 检索层评测 |
| `rag_answer_eval.py` | 答案生成（extractive + 4 LLM） |
| `rag_judge.py` / `rag_judge_retry.py` | LLM-as-judge 与失败重试 |
| `rag_judge_aggregate.py` | 指标汇总 |
| `evaluation/gold_qa.jsonl` | 24 条 gold QA |
| `evaluation/gold_retrieval_metrics.json` | 检索层结果 |
| `evaluation/answers.jsonl` | 各系统答案 |
| `evaluation/judged.jsonl` | 逐条裁判评分 |
| `evaluation/gold_answer_metrics.json` | 答案层汇总指标 |

## 8. 下一步

1. **人工复核 24 条 gold**（重点：5 条对抗探针、qwen 失败的边界案例、glm 早期截断 3 条已重生成需复核）；
2. **扩大 gold 集**：从 model_verified_candidates.csv（447 条）+ jury 交叉验证继续扩充可回答项，对抗探针扩到 ≥20；
3. **实体链接组件**：把 v3 的 subject_anchor 从"gold 字段提供"改为"问题自动抽取"（用 KG entities.csv 36+ 实体表），打通生产链路；
4. **条件保留专项**：针对 LLM condition_retention 0.59-0.65 的短板改提示（强制列条件清单）并用数值匹配自动评分；
5. **多裁判分歧仲裁**：exact 一致率 0.83 的分歧项（约 12 条）送人工裁决。
