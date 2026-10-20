# 五模型交叉验证与严格层 v2 构建报告（最终版）

> 本报告记录针对首轮评审发现的 P0 缺陷（mg/MG 实体混淆、客体跨句绑定、谓词顺序错误、条件未绑定、审计协议效度缺陷）的完整修复，以及 5 个国产大模型评审团对 v2 候选事实的三元组级交叉验证。目标：以"多模型共识 + 统计一致性 + 人工签核入口"逼近人工 golden 效果。

## 1. 修复清单与量化效果（v1 → v2）

| # | v1 缺陷 | v2 修复 | 量化效果 |
|---|---|---|---|
| F1 | 单位 mg / 添加剂 MG(孔雀石绿) / 元素 Mg 折叠为同一实体，卷入 61/119 条关系 | 缩写表大小写敏感 + 单位后缀守卫（`mg` 后跟 `/L` 视为单位非实体） | 幽灵实体事实 **61 → 0** |
| F2 | 同物异名不融合；`Cl−`、`Cl<sup>−</sup>`、`$\mathrm{Cl^-}$` 全部漏识别 | 确定性别名表 + 上下标/LaTeX 化学式归一 | 氯离子实体从 0 提及恢复为活跃实体；synergizes_with 恢复抽取 |
| F3 | 客体可从整行任意位置取（跨句错绑，如 "ZPS accelerates … object=mg"） | 主体、客体都必须出现在谓词所在子句内 | 跨句错绑消除 |
| F4 | accelerates 判定先于 improves，"enhance the filling performance" 被错判为 accelerates_deposition | 谓词顺序：synergizes → improves_filling → inhibits → accelerates → used_as_* → adsorbs_on；enhance 移出加速触发词 | improves_filling 26 → 54 条 |
| F5 | 条件完全不绑定事实（1,295 条数值悬空，论文核心创新只存在于文字） | 9 类条件槽（浓度/温度/电流密度/电位/pH/时间/转速/几何/百分比）子句优先、整行回退绑定 | 条件覆盖 **0% → 52.8%**（115/218 条事实带 403 条条件） |
| F6 | 中文段落从不切分（切分要求标点后有空格） | 中文标点直接切分子句 | 中文文献（马晓川学位论文等）关系可抽取 |
| F7 | 单位集窄 | 扩展 mol/L、ppm、pH、数值范围、Ω 等 | 单位覆盖 16 种 |
| F8 | 仅 5 类实体 | 12 类（Additive/Chemical/Metal/Method/Process/Via/Property/Electrolyte/Substrate/Mechanism/Role/Surface） | 实体 64 → 126 |
| F9 | 仅 4 种谓词 | 9 种（+used_as_leveler/suppressor/accelerator/inhibitor、adsorbs_on） | 候选事实 119 → 218 |
| F10 | 主体取子句第一个化学实体（常选错） | 主体 = 距谓词触发词最近的化学/添加剂实体 | 主语错选减少 |

## 2. v2 构建规模（48 篇文献实测）

| 数据类型 | v1 | v2 |
|---|---:|---:|
| 文档 | 48 | 48 |
| 证据片段 | 1,290 | 1,411 |
| 实体 | 64（5 类） | **126（12 类）** |
| 实体提及 | 3,216 | 5,350 |
| 数值/单位 | 1,295 | 1,778 |
| 候选关系 | 119（4 种谓词） | **218（9 种谓词）** |
| 条件记录（绑定到事实） | **0** | **403（覆盖 52.8% 事实）** |
| mg 幽灵实体事实 | 61 | **0** |

谓词分布：inhibits_deposition 66、improves_filling 54、used_as_inhibitor 29、accelerates_deposition 28、adsorbs_on 21、used_as_leveler 16、synergizes_with 2、used_as_accelerator 1、used_as_suppressor 1。

## 3. 五模型评审团设计

### 3.1 评审团构成（4 厂商 5 模型，防同源偏差）

| 模型 | 厂商 | 支持率（严格度排序） |
|---|---|---:|
| deepseek-v4-pro-0813 | DeepSeek | 44.95%（最严格） |
| glm-5.3-shouyun | 智谱 AI | 58.72% |
| qwen3.7-max | 阿里通义 | 60.55% |
| qwen3.6-plus | 阿里通义（不同代际） | 66.97% |
| kimi-k2.6 | 月之暗面 | 70.18%（最宽松） |

MiniMax-M3 在该路由持续 503（无可用 provider key），第 5 席改用 qwen3.6-plus。

### 3.2 审计协议的效度修复（核心）

v1 协议只送"谓词+证据"，模型自行重抽主客体 → 测得的是"证据是否支持某类关系存在"，而非"管线三元组是否正确"。实测恶例：管线抽 "JGB inhibits_deposition …"，模型自抽真主语 Cz-BPDB 判 supported，管线错误被计入 79.83% 的通过率。

v2 协议对**三元组本身**裁决：

```text
输入：subject_name + predicate + object_name + 管线抽取的 conditions + 证据原文
输出：label 五分类 + subject_correct / predicate_correct / object_correct 逐项布尔
      + corrected_*（修正建议）+ conditions（模型独立抽取）+ confidence + reason
```

### 3.3 工程要点

- temperature=0；max_tokens=8000（v1 用 900 时推理型模型思维链耗尽 token、正文为空，98/218 条失败——已定位修复）；
- content 为空时从 reasoning_content 兜底提取 JSON；
- 断点续跑：api_error 记录自动剔除重试；全程共 1,090 次调用全部完成。

## 4. 交叉验证结果（218 条 × 5 模型）

### 4.1 共识裁决

| 裁决 | 规则 | 数量 | 占比 |
|---|---|---:|---:|
| verified | ≥4/5 支持 + 主体/谓词/客体逐项过半正确 | 120 | 55.05% |
| quarantine | 3/5 支持（人工复核队列） | 21 | 9.63% |
| rejected | ≤2/5 支持或 ≥2 条 contradicted | 77 | 35.32% |

**验证率 55.05%，Wilson 95% CI [48.41%, 61.51%]**。这是三元组级的真实数字——对比 v1 声称的 79.83%（谓词级、协议有效度缺陷），宁可低 25 个百分点也要真实。

### 4.2 一致性统计

| 指标 | 数值 |
|---|---:|
| Fleiss' κ（五分类） | 0.5661（中等一致） |
| Fleiss' κ（二分类 supported/非） | 0.6379（实质性一致） |
| 成对 Cohen's κ 范围 | 0.42（deepseek↔kimi）– 0.73（qwen3.6↔qwen3.7） |

5 个模型来自 4 个独立厂商，一致性水平说明判定有系统性依据而非随机噪声；deepseek 与 kimi 之间 κ 最低（0.42）恰与其严格度极差（44.9% vs 70.2%）吻合。

### 4.3 按谓词的裁决分布

| 谓词 | 总数 | verified | quarantine | rejected | 验证率 |
|---|---:|---:|---:|---:|---:|
| used_as_leveler | 16 | 13 | 1 | 2 | 81.3% |
| used_as_inhibitor | 29 | 26 | 2 | 1 | 89.7% |
| adsorbs_on | 21 | 16 | 4 | 1 | 76.2% |
| improves_filling | 54 | 27 | 2 | 25 | 50.0% |
| inhibits_deposition | 66 | 24 | 8 | 34 | 36.4% |
| accelerates_deposition | 28 | 11 | 4 | 13 | 39.3% |

角色类谓词（used_as_*）验证率高——管线词典+角色触发词的模式对这类关系可靠；效应类谓词（inhibits/accelerates/improves）验证率 36–50%，错误集中在：主体归属（配合物 vs 组分）、对象粒度（wafer vs through-hole filling）、谓词语义（抑制水解 vs 抑制沉积）。**这正是下一版抽取器要主攻的方向。**

### 4.4 评审团质量抽检（对评审团的评审）

随机抽 5 条被拒事实，全部为管线真实错误：

1. `PUB2 improves_filling wafer`——客体粒度错（应为通孔填充）；
2. `SPS synergizes_with PEG`——证据说两者分别与 SA 协同，非彼此协同；
3. `Cl- inhibits_deposition Cu`——抑制主体是 PEG-Cu(I)-Cl⁻ 配合物而非 Cl⁻ 单独；
4. `PEG accelerates_deposition`——证据说 SPS 取代 PEG 来加速，PEG 是抑制剂；
5. `H2SO4 inhibits_deposition`——证据说抑制 Cu²⁺ 水解，非抑制金属沉积。

其中 32/77 条为五模型全票一致拒绝。评审团在三元组级抓真错误的能力得到实证。

### 4.5 共识条件融合

65/120 条 verified 事实带共识条件（管线条件 + 模型独立抽取条件按槽位融合投票）。示例：

```text
PEG improves_filling filling performance
  concentration = 200 ppm  （6 票：管线 + 全部 5 模型）
CMHT improves_filling Microvia
  time = 1 h; geometry = 150 μm, 80 μm, 19.1 μm
```

## 5. Golden Benchmark v2

- 随机种子 2025，8:2 划分：train 174 / test 44；
- 测试集标签分布：supported 30、unsupported 9、partial 3、ambiguous 1、contradicted 1；
- `gold_status = llm_panel_consensus_needs_human_signoff`；
- 位置：[golden_benchmark_v2/](golden_benchmark_v2/)（gold_test.jsonl / train_reference.jsonl / gold_reference.jsonl）。

诚实声明：这是**五模型共识基准**，仍不是双人专家金标准。人工签核入口见 §6。

## 6. 人工签核层（逼近 golden 的最后一步）

[jury/human_review_packet.csv](jury/human_review_packet.csv)：21 条 quarantine 全量 + verified/rejected 分层抽样（共 46 条），含空白 human_label 列。填写后运行：

```bash
python3 kg_pipeline/jury_consistency.py
```

输出 [jury/human_vs_panel.json](jury/human_vs_panel.json)（panel vs human 一致率、Cohen's κ、以人工为真值的 P/R）与 [jury/golden_final.jsonl](jury/golden_final.jsonl)（human_expert_signed 级 golden）。

### 6.1 LLM 预标注 Dry Run（已执行，2025-10-20）

在真人签核前，先用**评审团之外的两个大模型**（deepseek-v4-pro-preview 主标注 + kimi-k2.7-code 复核，均为评审团同族不同版本；路由上 gpt/claude 当时不可用）对 46 条签核包做**盲标**（不告知评审团任何结论，避免锚定），跑通全流程并得到初步数字。

**双标注员一致性（模拟双人 IAA）**：

| 指标 | 数值 |
|---|---:|
| 五分类 exact agreement | 65.22% |
| 五分类 Cohen's κ | 0.433 |
| 二分类（accepted/not）exact | 91.30% |
| 分歧条数 | 16/46 |

**评审团 vs 主标注员（46 条）**：

| 指标 | 数值 |
|---|---:|
| 五分类一致率 / κ | 67.39% / 0.379 |
| 二分类一致率 / κ | **93.48% / 0.784** |
| 评审团 verified 的精确率（vs 预标注） | **93.33%**（Wilson 95% CI [70.18%, 98.81%]） |
| 硬冲突（supported↔unsupported/contradicted） | 仅 2/46（4.3%） |

分歧结构分析：

- 15 条分歧中 11 条是 `supported→partial`：标注员认为"大体支持但有瑕疵"——**恰好印证评审团把这 21 条放入 quarantine 的判断**（quarantine 21 条被标注员判为 partial 11 条 + supported 10 条，全部落在边界区，无一被判 unsupported）；
- verified 抽样 15 条：标注员 14 supported + 1 unsupported（与 93.3% 精确率一致）；
- rejected 抽样 10 条：标注员 6 unsupported + 1 contradicted（70% 确认拒绝）+ 3 条"捞回"（其中 2 条是同一 `SA improves_filling void` 案例）；
- 2 条硬冲突均为真实的 schema 边界问题：
  - `NBT used_as_inhibitor`：中文文献"抑制剂"在电镀语境=沉积抑制剂，标注员按缓蚀剂理解——**schema 中 inhibitor/suppressor 术语边界需在签核指南中明确**；
  - `SA improves_filling void`：管线把客体抽成"void（空洞）"，评审团判 unsupported、标注员判 supported 但同时指出"客体应为填充过程而非空洞本身"——**发现 v2 抽取器新的客体粒度缺陷（v3 待修）**。

**Dry Run 结论**：流程端到端可用；评审团 `verified` 裁决可靠性高（93.3%）；`quarantine` 分层设计有效（边界区零误放）；两处 schema/抽取边界问题已被定位。产出 [jury/golden_final.jsonl](jury/golden_final.jsonl)（46 条，`gold_status=llm_pre_annotated_pseudo_gold`，**如实标记为 LLM 预标注伪金标准，非人工金标准**）。

复现命令：

```bash
python3 kg_pipeline/llm_signoff.py --base-url <URL> --api-key <KEY> \
  --primary deepseek-v4-pro-preview --secondary kimi-k2.7-code
python3 kg_pipeline/jury_consistency.py
```

## 7. 图谱落库（Neo4j 5.x，实测通过）

```bash
python3 kg_pipeline/export_v2_csv.py          # 已执行
cypher-shell -u neo4j -p <pwd> -f kg_pipeline/strict_neo4j_import_v2.cypher  # 已执行
```

导入后实测：StrictDocumentV2 48、StrictEvidenceV2 1,411、StrictEntityV2 126、StrictValueV2 1,778、StrictCandidateFactV2 218、StrictConditionV2 403、StrictPanelReviewV2 218；**悬空事实 0**；VerifiedFactV2 120 / QuarantineFactV2 21 / RejectedFactV2 77 标签就位。

条件感知查询示例（实测返回）：

```cypher
MATCH (f:VerifiedFactV2)-[:STRICT_SUBJECT_V2]->(s:StrictEntityV2)
MATCH (f)-[:STRICT_OBJECT_V2]->(o:StrictEntityV2)
OPTIONAL MATCH (f)-[:UNDER_CONDITION_V2]->(c:StrictConditionV2)
RETURN s.name, f.predicate, o.name, collect(c.slot + '=' + c.value + ' ' + c.unit)
```

→ `CMHT improves_filling Microvia [time=1h, geometry=150μm, 80μm, 19.1μm]`——**论文声称的"条件感知事实表示"现在真实存在于图中。**

## 8. PubChem 实体链接

15/35 化学与添加剂实体链接到 CID/SMILES/InChIKey（[strict_extraction_v2/pubchem_links.jsonl](strict_extraction_v2/pubchem_links.jsonl)）：MG(CID 11269)、PVP、SPS、MPS、JGB、DMG、CuSO₄、H₂SO₄、H₃BO₃、NaCl、Cl⁻ 等。其余为领域内部缩写（CMHT/PEP/ZPS/VMS/TPM 等）无 PubChem 条目，诚实标记 unresolved。

## 9. 交付物清单

| 文件 | 内容 |
|---|---|
| [kg_pipeline/strict_extract_v2.py](kg_pipeline/strict_extract_v2.py) | 修复 F1–F10 的严格抽取器 |
| [kg_pipeline/llm_jury.py](kg_pipeline/llm_jury.py) | 五模型评审团（三元组级协议、断点续跑） |
| [kg_pipeline/jury_aggregate.py](kg_pipeline/jury_aggregate.py) | 共识聚合 + Fleiss' κ + Wilson CI + golden v2 |
| [kg_pipeline/jury_consistency.py](kg_pipeline/jury_consistency.py) | 人工签核一致性回填 |
| [kg_pipeline/export_v2_csv.py](kg_pipeline/export_v2_csv.py) | Neo4j CSV 导出 |
| [kg_pipeline/strict_neo4j_import_v2.cypher](kg_pipeline/strict_neo4j_import_v2.cypher) | 图谱导入 + 12 条验证查询 |
| [kg_pipeline/entity_link_pubchem.py](kg_pipeline/entity_link_pubchem.py) | PubChem 实体链接 |
| [strict_extraction_v2/](strict_extraction_v2/) | v2 数据层（7 个 jsonl + CSV + summary） |
| [jury/](jury/) | 评审团原始记录 + 共识 + 三分类事实 + 签核包 |
| [golden_benchmark_v2/](golden_benchmark_v2/) | 共识 golden 基准 |
| [CROSS_VALIDATION_REPORT.md](CROSS_VALIDATION_REPORT.md) | 本报告 |
| [论文_KG构建与评测章节大纲_v2.md](论文_KG构建与评测章节大纲_v2.md) | 修订后的章节大纲 |

## 10. 结论与剩余限制

**已解决**：mg/MG 混淆（61→0）、客体跨句绑定、谓词顺序、条件绑定（0%→52.8%）、审计协议效度（三元组级裁决）、单模型自证（五模型跨厂商共识 + κ 统计）、虚无数字（55.05% + Wilson CI 替代 79.83%）、实体规范化（PubChem 链接）、条件表示落图（UNDER_CONDITION 边）。

**剩余限制（不隐瞒）**：
1. LLM 评审团 ≠ 双人专家金标准——签核包已就绪，dry run（§6.1）已用 LLM 预标注跑通，真人签核尚未执行；
2. 召回（漏抽）未测——需要独立 gold-coverage 文档集；
3. 效应类谓词验证率 36–50%，抽取器对"配合物整体 vs 组分"的主体归属仍需加强；dry run 还发现客体粒度缺陷（`improves_filling` 客体被抽成 void 而非填充过程）；
4. 下游 RAG 对照实验为后续工作。
