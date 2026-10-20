# ChemKG — 电镀领域知识图谱与 KG-RAG 问答系统

面向铜/钴电沉积、电镀添加剂与 PCB 通孔/盲孔填充领域文献的 **证据优先、条件感知** 知识图谱（KG）构建与检索增强生成（RAG）问答系统。本仓库为毕业论文配套代码，包含三部分：

| 模块 | 目录 | 说明 |
| --- | --- | --- |
| KG-RAG 问答系统 | [`kgrag/`](kgrag/) | 工程化重构后的系统包：FastAPI 后端 + 原生 Web 前端，src layout、类型化配置、pytest 测试 |
| KG 构建管线 | [`kg_pipeline/`](kg_pipeline/) | 严格规则抽取 → 实体链接（PubChem）→ 五模型评审团 → 人工签核 → Neo4j 导入 |
| 实验与评测 | [`experiments/`](experiments/) + [`evaluation/`](evaluation/) | 检索层/答案层评测、基线对比（闭卷、LLM 直抽）、LLM-as-judge 脚本与全部评测数据 |

毕业论文（KG 与 KG-RAG 系统章节最终版）见 [`docs/论文_KG与KG-RAG系统章节.md`](docs/论文_KG与KG-RAG系统章节.md)。

---

## 1. 系统概览

- **知识表示**：`事实 = 主体 + 关系 + 客体 + 条件（浓度/电位/温度/几何/…）+ 证据 + 审核状态`，每条事实可回溯原文证据；
- **质量控制**：候选事实经五模型评审团交叉验证（Fleiss' κ / 成对 Cohen's κ）+ 人工签核，分为 verified / quarantine / rejected 三层；
- **检索策略**：纯词法 BM25、KG 增强（默认）、主体锚定、保守图扩展，支持评审状态意图路由与诚实弃答；
- **答案生成**：证据优先提示词，流式 SSE 输出，结论逐条标注 `evidence_id` 引用，支持 OpenAlex 联网学术检索；
- **评测体系**：检索层（Hit@k / Evidence Recall@k / Sufficient@k）与答案层（多评委 LLM-as-judge）统一 gold 集评测。

## 2. 仓库结构

```
ChemKG/
├── kgrag/                     # KG-RAG 问答系统（工程化软件包，详见 kgrag/README.md）
│   ├── pyproject.toml         # 包元数据与依赖（pip install -e .）
│   ├── run.py                 # 免安装启动入口
│   ├── src/kgrag/             # config / schemas / textproc / kgio / index / retrieval / generation / api / cli
│   ├── web/                   # 聊天前端（原生 HTML/CSS/JS）
│   ├── scripts/               # 检索评测脚本
│   └── tests/                 # pytest 测试
├── kg_pipeline/               # KG 构建管线（详见 kg_pipeline/README.md）
│   ├── strict_extract.py      # v1 严格规则抽取
│   ├── strict_extract_v2.py   # v2 严格抽取（条件槽、跨符号融合）
│   ├── entity_link_pubchem.py # PubChem 实体链接
│   ├── llm_jury.py            # 五模型评审团
│   ├── jury_aggregate.py      # 共识聚合（κ 统计、golden 基准划分）
│   ├── jury_consistency.py    # 人工签核 vs 评审团一致性
│   ├── export_v2_csv.py       # 六表 CSV 导出
│   └── *.cypher               # Neo4j schema / 导入 / 审计查询
├── experiments/               # 评测与基线实验脚本（详见 experiments/README.md）
├── evaluation/                # gold/silver 评测集与全部指标产物（含指标定义 README）
├── jury/                      # 评审团共识、逐模型评审、签核一致性产物
├── strict_extraction*/        # v1 / v2 / verify 抽取层数据（JSONL + CSV + summary）
├── golden_benchmark*/         # v1 / v2 golden 基准（train/test 划分）
├── kg_data/                   # v1 KG 六表（运行系统默认知识库）
├── kg_v2_unified/             # v2 统一 KG 六表（含评审状态增强列）
└── docs/                      # 毕业论文章节（最终版）
```

> 文献原文（PDF）与 BM25 索引等大体量/可再生产物不入库：索引可用一条命令重建（见下），文献库因版权原因不公开。

## 3. 快速开始

### 3.1 安装与索引构建

```bash
# Python >= 3.10
cd kgrag
pip install -e '.[dev]'

# 从 KG 六表构建 BM25 索引（输出到 ../rag_index）
python -m kgrag.cli build --kg ../kg_data --out ../rag_index
# 或使用 v2 统一知识库
python -m kgrag.cli build --kg ../kg_v2_unified --out ../rag_index_v2
```

### 3.2 配置与启动

```bash
cp .env.example .env   # 填入 KGRAG_LLM_BASE_URL / KGRAG_LLM_API_KEY / KGRAG_LLM_MODEL
python run.py          # 默认 http://0.0.0.0:8600 ，浏览器打开即进入问答界面
```

### 3.3 运行测试

```bash
cd kgrag && pytest
```

## 4. 实验复现

评测脚本统一从仓库根目录运行，默认路径与仓库布局一致。例如统一 gold 检索层评测：

```bash
python experiments/gold_unified_eval.py          # 读 rag_index_* / evaluation/gold_qa_*.jsonl
python experiments/rag_answer_eval.py --index rag_index_v2 --gold evaluation/gold_qa_v2.jsonl
python experiments/rag_judge_aggregate.py        # 汇总评委打分为最终指标
```

各实验（闭卷基线、LLM 直抽基线、稠密检索对照、弃答率等）的命令与产物对应关系见 [`experiments/README.md`](experiments/README.md)；指标口径定义见 [`evaluation/README.md`](evaluation/README.md)。

KG 构建完整流程（抽取 → 评审 → 签核 → 导出 → Neo4j 导入）见 [`kg_pipeline/README.md`](kg_pipeline/README.md)。

## 5. 环境变量

| 变量 | 用途 |
| --- | --- |
| `KGRAG_LLM_BASE_URL` / `KGRAG_LLM_API_KEY` / `KGRAG_LLM_MODEL` | 问答系统 LLM（OpenAI 兼容接口） |
| `KGRAG_INDEX` | 索引目录（默认 `../rag_index`） |
| `KGRAG_API_KEY` | 服务端访问密钥（对外暴露时务必设置） |
| `KG_LLM_BASE_URL` / `KG_LLM_API_KEY` / `KG_LLM_MODEL` | KG 管线 LLM 抽取/评审 |

> 任何真实密钥均不得提交；`.env` 已在 `.gitignore` 中排除。

## 6. 许可

MIT License，见 [LICENSE](LICENSE)。
