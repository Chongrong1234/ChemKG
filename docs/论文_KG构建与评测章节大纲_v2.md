# 第 X 章 领域知识图谱构建与质量评测（v2，叙述与实现一致）

> 本章作为毕业论文"方法与实验"部分的半章内容。研究对象为铜/钴电沉积、电镀添加剂及 PCB 通孔/盲孔填充领域。v2 版大纲与实际产出严格对齐：所有表格数字均来自 [strict_extraction_v2/summary.json](strict_extraction_v2/summary.json) 与 [jury/agreement_summary.json](jury/agreement_summary.json) 的实测结果。

## X.1 研究目标与总体思路

电镀与电化学文献中的科学事实高度依赖实验条件：某添加剂对沉积行为的影响往往只在特定浓度、电位、pH 或孔结构下成立。若将知识表示为无条件三元组，会造成"条件性结论被泛化为普适知识"的系统性错误。

因此本文将领域事实表示为：

```text
事实 = 主体 + 关系 + 客体 + 条件(浓度/电位/温度/几何/…) + 证据 + 审核状态
```

构建目标：(1) 实体识别与规范化（含跨符号形式融合与外部数据库链接）；(2) 关系抽取（角色类与效应类谓词）；(3) 实验条件逐条绑定到事实；(4) 证据绑定与可回溯；(5) 五模型交叉验证 + 人工签核的质量分层；(6) Neo4j 条件感知图谱存储与查询。

总体流程：

```text
领域文献(48篇)
  → 文档解析与清洗
  → 严格领域筛选(领域词门控 + 跨领域污染排除 + 参考文献过滤)
  → 大小写敏感的实体识别 + 别名融合 + 化学符号归一
  → 数值/单位/条件槽抽取
  → 子句级关系抽取(主体/客体同子句 + 距触发词最近主体)
  → 条件绑定(子句优先、整行回退)
  → 候选事实(218条)
  → 五模型评审团交叉验证(三元组级裁决, 1090次调用)
  → Verified(120) / Quarantine(21) / Rejected(77)
  → 人工签核入口(46条签核包)
  → Neo4j 条件感知图谱
```

## X.2 领域 Schema 设计（12 类实体 / 9 种谓词，全部落地）

### X.2.1 实体类型（实际实现 12 类）

| 实体类型 | 示例（图中实际存在） |
|---|---|
| Additive | CMHT、PEP、SPS、JGB、PVP、ZPS、MPS、NBT、MG、DB、TPM、Cz-BPDB、AB1… |
| Chemical | CuSO₄、H₂SO₄、H₃BO₃、NaCl、Cl⁻、I⁻、Co(II) |
| Metal | Cu、Co、Ni |
| Method | CV、EIS、GM、XRD、SEM、XPS、EQCM、Raman |
| Process | 电镀、电沉积、超共形、bottom-up |
| Via | 通孔、盲孔、微盲孔、沟槽、TH、Microvia |
| Property | 填充性能、填充率、过电位、极化、空洞、FR |
| Electrolyte | 镀液、电解液、plating bath |
| Substrate | PCB、晶圆、基板 |
| Mechanism | 吸附、成核、传质、扩散、钝化 |
| Role | leveler、suppressor、accelerator、inhibitor |
| Surface | electrode surface |

实体规范化包含三层：① Unicode/大小写/单位归一（μm/µm/um、Cl−/Cl-）；② 确定性别名融合（孔雀石绿→MG、copper sulfate→CuSO₄）；③ **大小写敏感守卫**（区分单位 mg、添加剂 MG、元素 Mg——v1 曾因此产生卷入 61/119 条关系的幽灵实体，v2 归零）。化学符号归一覆盖 `Cl−`、`Cl<sup>−</sup>`、`$\mathrm{Cl^-}$` 等文献排版变体。

### X.2.2 谓词类型（9 种，全部实现）

```text
角色类：used_as_leveler / used_as_suppressor / used_as_accelerator / used_as_inhibitor
效应类：inhibits_deposition / accelerates_deposition / improves_filling
协同类：synergizes_with
界面类：adsorbs_on
```

每种谓词定义了触发词、领域上下文约束和判定顺序（协同 → 填充 → 抑制 → 加速 → 角色 → 吸附），修复了 v1 中 "enhance the filling performance" 因判定顺序错误被归为 accelerates_deposition 的缺陷。

### X.2.3 条件感知的事实表示（核心创新，已落图）

9 类条件槽：concentration / temperature / current_density / potential / pH / time / rotation / geometry / percentage。条件从谓词所在子句优先抽取、整行回退（并标注 scope），通过 `UNDER_CONDITION` 边绑定到事实节点。

```text
(:StrictCandidateFact)-[:UNDER_CONDITION]->(:StrictCondition {slot, value, unit, scope})
```

实测：218 条候选事实中 115 条（52.8%）绑定 403 条条件记录。

## X.3 文献预处理与严格领域筛选

输入为 48 篇已清洗领域文献（full.md，保留行号）。筛选规则：领域词门控（电镀/电沉积/通孔/盲孔/填充等）、跨领域排除（催化、CVD、CMP、光催化、腐蚀、交叉偶联）、参考文献/DOI/URL 行过滤。文档标题参考文献段之后整段跳过。

## X.4 实体识别与规范化

识别采用领域词典 + 正则，关键工程点：

1. **缩写大小写敏感**：`MG`（孔雀石绿）、`mg`（毫克单位）、`Mg`（镁）严格区分；单位后缀守卫（`mg` 后跟 `/L` 判为单位）；
2. **别名融合**：中英文全称与缩写映射到同一规范实体；
3. **排版变体归一**：`Cl<sup>−</sup>`、`$\mathrm{Cl^-}$`、`Cl −` 均归一为 Cl⁻ 实体；
4. **PubChem 链接**：35 个化学/添加剂实体中 15 个链接到 CID/SMILES/InChIKey（malachite green→CID 11294 等）；领域内部缩写（CMHT/PEP/ZPS 等）无 PubChem 条目，诚实标记 unresolved。

## X.5 关系与条件抽取

- 关系候选限定在子句内：主体与客体都必须出现在谓词触发词所在子句（消除 v1 的跨句错绑）；
- 主体选择：距谓词触发词最近的化学/添加剂实体（替代 v1 的"第一个"）；
- 谓词语义约束：inhibits/accelerates 需沉积语境、improves 需填充语境、synergizes 需双实体、加速与析氢(HER)语境分离；
- 条件绑定：子句内条件优先，同槽位缺失时从整行回退并标注 scope。

## X.6 证据优先的事实组织

Neo4j 严格层（v2）：

```text
(:StrictDocumentV2)-[:STRICT_HAS_EVIDENCE_V2]->(:StrictEvidenceV2)
(:StrictEvidenceV2)-[:STRICT_MENTIONS_V2]->(:StrictEntityV2)
(:StrictEvidenceV2)-[:STRICT_REPORTS_VALUE_V2]->(:StrictValueV2)
(:StrictCandidateFactV2)-[:STRICT_SUPPORTED_BY_V2]->(:StrictEvidenceV2)
(:StrictCandidateFactV2)-[:STRICT_SUBJECT_V2]->(:StrictEntityV2)
(:StrictCandidateFactV2)-[:STRICT_OBJECT_V2]->(:StrictEntityV2)
(:StrictCandidateFactV2)-[:UNDER_CONDITION_V2]->(:StrictConditionV2)
(:StrictCandidateFactV2)-[:PANEL_REVIEWED_BY_V2]->(:StrictPanelReviewV2)
```

事实状态：`StrictCandidateFactV2 → :VerifiedFactV2(120) / :QuarantineFactV2(21) / :RejectedFactV2(77)`，状态叠加标签、不覆盖候选记录。

### X.6.1 构建规模

**表 X-1 严格证据层 v2 构建规模（48 篇文献实测）**

| 数据类型 | v1 | v2 |
|---|---:|---:|
| 文档 | 48 | 48 |
| 证据片段 | 1,290 | 1,411 |
| 实体 | 64（5 类） | 126（12 类） |
| 实体提及 | 3,216 | 5,350 |
| 数值/单位 | 1,295 | 1,778 |
| 候选关系 | 119（4 谓词） | 218（9 谓词） |
| 事实绑定条件 | 0 | 403（覆盖 52.8%） |
| mg 幽灵实体 | 61 条事实 | 0 |

## X.7 质量评测：五模型交叉验证

### X.7.1 评测协议（三元组级，修正单模型自证）

v1 的单模型审计只送"谓词+证据"，模型自行重抽主客体，测得的是"证据是否支持某类关系存在"，系统性高估管线精度。v2 协议将管线抽取的 subject/predicate/object/conditions 一并送审，由评审团对**三元组本身**逐项裁决（label + subject_correct/predicate_correct/object_correct + 修正建议 + 独立条件抽取）。

评审团构成（4 厂商 5 模型，防同源偏差）：deepseek-v4-pro-0813（DeepSeek）、glm-5.3-shouyun（智谱）、qwen3.7-max 与 qwen3.6-plus（阿里，两代际）、kimi-k2.6（月之暗面）。temperature=0，每条事实 5 模型独立评审，共 1,090 次调用。

### X.7.2 共识裁决结果

**表 X-2 五模型共识裁决分布（218 条候选事实）**

| 裁决 | 判定规则 | 数量 | 占比 |
|---|---|---:|---:|
| verified | ≥4/5 支持 + 主体/谓词/客体逐项过半 | 120 | 55.05% |
| quarantine | 3/5 支持 | 21 | 9.63% |
| rejected | ≤2/5 支持或 ≥2 contradicted | 77 | 35.32% |

验证率 55.05%（Wilson 95% CI [48.41%, 61.51%]）。

**表 X-3 按谓词的裁决分布**

| 谓词 | 总数 | verified | quarantine | rejected | 验证率 |
|---|---:|---:|---:|---:|---:|
| used_as_inhibitor | 29 | 26 | 2 | 1 | 89.7% |
| used_as_leveler | 16 | 13 | 1 | 2 | 81.3% |
| adsorbs_on | 21 | 16 | 4 | 1 | 76.2% |
| improves_filling | 54 | 27 | 2 | 25 | 50.0% |
| accelerates_deposition | 28 | 11 | 4 | 13 | 39.3% |
| inhibits_deposition | 66 | 24 | 8 | 34 | 36.4% |

角色类谓词可靠（76–90%）；效应类谓词 36–50%，错误集中于主体归属（配合物 vs 组分）、客体粒度（wafer vs 通孔填充）、谓词语义（抑制水解 vs 抑制沉积）。

### X.7.3 评审团一致性与质量抽检

| 指标 | 数值 |
|---|---:|
| Fleiss' κ（五分类） | 0.5661 |
| Fleiss' κ（二分类） | 0.6379 |
| 成对 Cohen's κ | 0.42–0.73 |
| 单模型支持率范围 | 44.95%（deepseek）– 70.18%（kimi） |

对被拒事实的随机抽检（5/5 为管线真实错误，32/77 条五模型全票一致拒绝）证实评审团在三元组级抓真错误的能力。

### X.7.4 共识条件融合

65/120 条 verified 事实带共识条件：管线条件与 5 模型独立抽取的条件按槽位融合投票（如 "concentration=200 ppm" 获管线+5 模型共 6 票）。

### X.7.5 Golden Benchmark v2

种子 2025、8:2 划分：train 174 / test 44（supported 30、unsupported 9、partial 3、ambiguous 1、contradicted 1）。`gold_status=llm_panel_consensus_needs_human_signoff`。

### X.7.6 人工签核层与 LLM 预标注 Dry Run

46 条签核包（21 条 quarantine 全量 + verified/rejected 分层抽样）。真人填写 human_label 后，[jury_consistency.py](kg_pipeline/jury_consistency.py) 计算评审团 vs 人工的 Cohen's κ 与以人工为真值的 P/R，生成 human_expert_signed 级 golden。

在真人签核前，本文先用评审团之外的两个大模型（deepseek-v4-pro-preview + kimi-k2.7-code，盲标、不告知评审团结论）对签核包做预标注 dry run：双标注员二分类一致率 91.3%；评审团 verified 裁决相对独立预标注的精确率 93.33%（Wilson 95% CI [70.2%, 98.8%]）；46 条中硬冲突仅 2 条（均为 schema 术语边界与客体粒度问题，已被定位）。该 dry run 验证了签核流程的端到端可用性与评审团裁决的可靠性；其产出如实标记为 `llm_pre_annotated_pseudo_gold`，不冒充人工金标准。

## X.8 章节小结

本章构建了一个证据优先、条件感知的电镀领域知识图谱。相对直接三元组抽取的朴素方法，本文的三个方法学贡献为：① 事实表示将实验条件作为一等公民绑定到事实节点（UNDER_CONDITION 边，52.8% 覆盖），避免条件性结论被泛化；② 实体识别通过大小写敏感守卫、别名融合与排版变体归一消除化学实体混淆（mg/MG 幽灵实体 61→0），并链接 PubChem 外部标识；③ 质量评测采用跨厂商五模型评审团的三元组级交叉验证，以 55.05%（Wilson 95% CI [48.4%, 61.5%]）的共识验证率、Fleiss' κ=0.566 的一致性统计和 46 条人工签核入口替代单模型自证。局限与后续工作：召回测量需独立 gold-coverage 文档集；效应类谓词的主体归属判定需加强；双人专家签核与下游 RAG 对照实验为后续工作。
