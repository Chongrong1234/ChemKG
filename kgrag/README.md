# KG-RAG 电镀文献问答系统（工程化重构版）

基于电镀领域文献知识图谱的证据优先 RAG 问答系统，包含 **规范化后端服务** 与 **Web 问答前端**。
本工程是对原 `rag_system.py` / `rag_api.py` 平铺脚本的软件工程化重构，复用既有 `kg_data` 知识库与 `rag_index` 索引。

---

## 1. 功能总览

- **知识库问答**：基于 4,341 条文献证据、48 篇电镀领域文献（抑制剂、整平剂、超填充机理等）
- **四种检索策略**：纯词法 BM25 / KG 增强（默认）/ 主体锚定 / 图扩展
- **联网学术检索**：OpenAlex 白名单期刊（Electrochimica Acta、ACS Omega、Small 等 11 本），本地 + 网络综合分析证据至 20 条
- **Agent 过程展示**：流式推送检索阶段状态（本地检索 → 英文检索式生成 → 联网检索 → 综合分析），思考链（CoT）实时可见
- **流式回答**：SSE 实时推送——证据先达（亚秒级），随后思考过程与正文逐字输出
- **证据可回溯**：每个结论标注 `evidence_id` 引用，点击引用徽标高亮对应证据卡片，附上下文窗口与原文出处
- **诚实弃答**：问题指名知识库不存在的实体时明确拒答，不编造（本地与联网均无结果才弃答）
- **深度思考开关**：DeepSeek reasoning 模型可开/关思考（关闭后约提速 6 倍）
- **多会话管理**：前端支持多个对话历史（localStorage 持久化）
- **完整 REST API**：非流式 / 流式 / 证据详情 / 健康检查 / 指标统计

## 2. 目录结构

```
kgrag/
├── pyproject.toml          # 包元数据、依赖、构建配置
├── run.py                  # 免安装启动入口（python run.py）
├── .env / .env.example     # 运行配置（密钥在 .env，勿提交）
├── src/kgrag/              # 源码（src layout）
│   ├── config.py           # 配置管理（环境变量 + .env，KGRAG_ 前缀）
│   ├── schemas.py          # 领域模型（EvidenceRow / RetrievalHit / 请求响应）
│   ├── textproc.py         # 中英混合分词（jieba + 停用词）
│   ├── kgio.py             # KG CSV 六表读取（documents/evidence/facts/...）
│   ├── index/
│   │   ├── builder.py      # BM25 倒排索引构建（兼容既有 index.json v2 格式）
│   │   └── store.py        # 索引加载与运行时只读视图
│   ├── retrieval/
│   │   ├── bm25.py         # Okapi BM25 词法检索
│   │   ├── kgboost.py      # KG 感知加权（实体 idf 提权 / 关系词匹配 / 主实体锚定）
│   │   ├── graphexp.py     # 保守图扩展（沿谓词与共享实体）
│   │   └── pipeline.py     # 检索流水线（策略编排 + 弃答守卫 + 邻居窗口）
│   ├── generation/
│   │   ├── llm.py          # OpenAI 兼容客户端（流式 / 非流式 / thinking 开关）
│   │   └── prompts.py      # 证据优先提示词 + 证据摘录式兜底
│   ├── service.py          # QAService 问答编排（检索→生成→引用）
│   ├── api/app.py          # FastAPI 工厂（REST + SSE + 静态托管）
│   └── cli.py              # 命令行（build / ask / serve）
├── web/                    # 前端（原生 HTML/CSS/JS，无构建依赖）
│   ├── index.html          # 聊天界面
│   ├── css/app.css
│   └── js/app.js           # SSE 流式解析 / 引用联动 / 多会话 / 设置
├── scripts/
│   └── eval_retrieval.py   # 检索回归评测（recall@k / hit@k）
└── tests/                  # pytest 单元测试（21 项）
```

## 3. 快速开始

### 3.1 环境要求

Python ≥ 3.10，依赖：`fastapi uvicorn pydantic sse-starlette python-dotenv httpx jieba`（均已在当前 conda 环境就绪）。

### 3.2 配置

首次使用复制 `.env.example` 为 `.env` 并填写 LLM 凭据（本机已配置好）：

```ini
KGRAG_LLM_BASE_URL=https://api.epicllmrouter.top/v1
KGRAG_LLM_API_KEY=sk-xxxx
KGRAG_LLM_MODEL=deepseek-v4-pro-0813   # DS 模型；支持其它 OpenAI 兼容模型
KGRAG_INDEX=../rag_index               # 索引目录（相对本工程根）
KGRAG_PORT=8600
```

### 3.3 启动

```bash
cd kgrag
python3 run.py                # 开发启动（自动加 src 到 sys.path）
# 或安装后使用入口
pip install -e . && kgrag-serve
```

浏览器打开 **http://127.0.0.1:8600** 即可问答。

### 3.4 命令行使用

```bash
PYTHONPATH=src python3 -m kgrag.cli ask --question "PVP 在钴电沉积中起什么作用？"
PYTHONPATH=src python3 -m kgrag.cli ask --question "..." --strategy anchored --subject PVP --topk 5
PYTHONPATH=src python3 -m kgrag.cli build --kg ../kg_data --out ../rag_index   # 重建索引
```

## 4. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活与索引状态 |
| GET | `/api/meta` | 元信息（策略表 / 模型 / 索引统计） |
| POST | `/api/ask` | 非流式问答（JSON → JSON） |
| POST | `/api/ask/stream` | **SSE 流式问答**（见下） |
| GET | `/api/evidence/{id}` | 证据详情（含上下文窗口） |
| GET | `/api/metrics` | 请求 / 错误 / 弃答 / 兜底计数 |

**SSE 事件序列**（`POST /api/ask/stream`）：

```
event: evidence          # 检索完成即推送（含得分/谓词/匹配词/邻居窗口）
data: [ {...}, ... ]

event: reasoning         # 思考增量（开启深度思考时）
data: 思考片段…

event: content           # 正文增量（含 [ev_xxx] 引用标注）
data: 片段…

event: done              # 汇总（延迟统计 / 弃答标记 / 模型名）
data: {"answer": "...", "latency_ms": ..., "retrieval_ms": ..., ...}
```

请求体字段：`question`（必填）、`strategy`、`topk`、`window`、`subject`（anchored 锚点）、`predicate_hint`、`doc_id`、`history`（追问上下文，最近 3 轮）、`thinking`（深度思考开关）。

## 5. 检索策略说明

| 策略 | 机制 | 适用 |
|---|---|---|
| `lexical` | 纯 Okapi BM25 | 基线对照 |
| `kg`（默认） | BM25 + 实体/关系/数值加权 + **主实体 idf 乘法提权** | 绝大多数问题 |
| `anchored` | kg + 主体锚定重排（subject 并入检索词，含主体证据 ×2.5 提权） | 问题指明材料名 |
| `graph` | kg + 沿谓词与共享实体的保守图扩展 | 需要更多关联证据 |

**弃答守卫**：问题含拉丁实体词且全部不在索引词表 → 直接弃答（`abstained: true`），不调用 LLM。联网检索开启时，本地弃答但网络期刊有结果则用网络证据作答，本地与联网均空才弃答。

### 5.1 联网学术检索（`web_search`）

问答请求可带 `"web_search": true`（前端设置面板默认开启），流程：

1. **本地知识库检索**（top-k 可调，默认 8）
2. **LLM 转写英文检索式**：如「PVP 在钴电沉积中起什么作用？」→ `polyvinylpyrrolidone PVP cobalt electrodeposition additive`
3. **OpenAlex 白名单期刊检索**：ISSN 过滤 11 本目标期刊（Journal of Electroanalytical Chemistry、Electrochimica Acta、ACS Omega、Colloids and Surfaces A、Chemical Engineering Journal、Small、ACS AMI、J. Mater. Chem. A/C、Applied Surface Science、J. Alloys Compd.），只收带摘要文献，DOI 去重，10 分钟结果缓存
4. **合并分析**：本地证据优先 + 网络证据补足至 **20 条**上限，网络证据带期刊/年份/作者/DOI，引用格式 `[web_xxxxxxxx]`，前端卡片可点击 DOI 打开原文

网络证据为「文献摘要」而非全文；检索失败静默降级为仅本地证据，绝不中断问答。

Agent 过程事件（SSE `status` 事件，供过程面板/CoT 展示）：`local`（本地检索）→ `web_query`（检索式生成）→ `web`（联网检索，含期刊列表）→ `generate`（综合分析，含本地/网络计数）。

相关配置：`KGRAG_WEB_SEARCH`（默认开）、`KGRAG_WEB_TIMEOUT`（20s）、`KGRAG_WEB_MAX`（网络证据上限 12）、`KGRAG_EVIDENCE_TOTAL`（总证据上限 20）。

## 6. 相对原系统的改进（经回归评测验证）

在既有评测集（silver 自动生成，仅作回归护栏）上的对比：

| 评测集 | 指标 | 原系统 | 重构版 |
|---|---|---|---|
| auto_silver (400) | Recall@5 | 0.9875 | **1.0000** |
| auto_anchored_silver (400) | Recall@5 | 0.9825 | **0.9950** |
| auto_entity_silver (237) | Hit@5 | 0.5408（历史记录） | **0.6009** |

工程层面的修复与增强：

1. **修复排序缺陷**：KG 加权后未按新分数重排，导致 top-k 截断仍按词法顺序（实体提权失效的根因）；
2. **主实体 idf 提权**：问题中判别力最强的实体词（如 PVP/JGB）对含该实体的证据做乘法提权，解决"材料缩写被高频通用词（钴/电沉积）淹没"；
3. **anchored 策略修复**：`subject` 并入检索词，泛指问题（"这种添加剂…"）也能命中主体证据；
4. **SSE 真实时流式**：线程池执行问答编排 + `asyncio.Queue` 桥接，检索完（亚秒级）即推送证据；
5. **thinking 开关**：DeepSeek reasoning 模型可关闭思考（实测 61s → 9.4s），`max_tokens` 提至 8192 防思考链耗尽正文配额；
6. **分层解耦**：配置 / 分词 / 索引 / 检索 / 生成 / 编排 / API 七层清晰，均带类型注解与 docstring，21 项单元测试覆盖。

复现评测：

```bash
python3 scripts/eval_retrieval.py --gold ../evaluation/auto_silver.jsonl --strategy kg --k 5
```

## 7. 测试

```bash
cd kgrag && python3 -m pytest tests/ -v
# 21 passed：分词 / 检索策略 / 弃答 / 序列化 / 服务编排 / API 全链路（离线替身 LLM）
```

## 8. 安全与部署注意

- `.env` 含 API 密钥，已列入 `.gitignore`，**勿提交版本库**；密钥仅存在于服务端，前端不接触
- 对外暴露时务必设置 `KGRAG_API_KEY`（请求需带 `X-API-Key` 头）并置于反向代理之后
- `KGRAG_RATE_LIMIT` 限流与 HTTPS 终止建议在 nginx/traefik 层完成
- 候选事实（CandidateFact）不自动等同于科学结论——系统始终返回原文证据与 `evidence_id` 以供人工核对

## 9. 公网穿透部署（SakuraFrp）

系统已通过 SakuraFrp 隧道暴露公网，当前访问地址：

| 入口 | 地址 |
| --- | --- |
| **公网（推荐）** | https://frp-arm.com:41005 |
| 运营商线路 | 电信 `dx.frp-arm.com:41005` / 联通 `lt.frp-arm.com:41005` / 移动 `yd.frp-arm.com:41005` |
| 本机调试 | http://127.0.0.1:8600 |

- 节点对**明文 HTTP 做强制拦截**（合规要求），公网访问必须走 HTTPS
- 隧道启用 frpc `auto_https = auto`：由 frpc 以节点域名自签证书终结 TLS，再明文反代本地 8600 端口，前端零改动
- 证书为自签（SakuraFrp Automatic TLS），浏览器提示"不安全"属预期，选择 **高级 → 继续访问** 即可；如需消除告警可按[官方文档](https://doc.natfrp.com/frpc/ssl.html)配置正规证书
- 免费节点限速 24 Mbit/s

### 9.1 部署构成

```
frp/
├── frpc.ini        # 隧道配置（本地 127.0.0.1:8600 -> 远程 41005, auto_https=auto）
├── frpc.log        # frpc 运行日志
└── start_all.sh    # 一键启动/自愈脚本（服务 + 隧道）
```

frpc 二进制位于 `~/.local/bin/frpc-sakura`（v0.51.0-sakura-15，由官方 Docker 镜像 `natfrp.com/frpc` 提取）。

### 9.2 日常运维（systemd 常驻）

服务已注册为系统级 systemd 单元，**开机自启 + 崩溃自动拉起（Restart=always，5 秒）**：

| 单元 | 作用 |
| --- | --- |
| `kgrag.service` | 本地问答服务（`python3 run.py`，127.0.0.1:8600） |
| `kgrag-frpc.service` | SakuraFrp 公网隧道（`frpc-sakura -c frpc.ini`，依赖 kgrag.service） |

```bash
# 状态一览（含本地/公网健康检查）
bash frp/start_all.sh              # 等价于 status

# 常用操作
bash frp/start_all.sh restart       # 重启全部（改代码/.env/frpc.ini 后）
bash frp/start_all.sh stop|start    # 停止/启动
bash frp/start_all.sh logs          # 跟踪实时日志（journalctl）

# 直接用 systemd
sudo systemctl status kgrag kgrag-frpc
sudo journalctl -u kgrag -f         # 服务日志（stdout/stderr 全部进 journal）
sudo systemctl disable --now kgrag-frpc kgrag   # 取消常驻
```

> 服务由 systemd 守护后，**不再需要**手动 `nohup python3 run.py` / `start_all.sh` 拉起；机器重启后自动恢复。

> **安全提醒**：当前 `KGRAG_API_KEY` 为空，公网上任何人都能调用问答（消耗 LLM 额度）。如需加锁：在 `.env` 设置 `KGRAG_API_KEY=<密钥>` 后重启服务，并在前端设置面板填入同一密钥（`X-API-Key` 头）。

### 9.3 用户自带模型接口（配置接口）

前端「设置 → 模型接口」允许每个使用者自带 OpenAI 兼容接口（API 地址 / API Key / 模型名），**留空字段自动回退服务端默认**；配置保存在浏览器 localStorage，问答请求随 body 携带 `llm` 字段，服务端按请求级覆盖构造客户端（不落盘、不污染全局配置）。

| 端点 | 说明 |
| --- | --- |
| `GET /api/llm/defaults` | 服务端默认配置（Key 脱敏为 `sk-d7…u2ia` 形式，不泄露原文） |
| `POST /api/llm/test` | 测试接口连通性：发一个 16-token 小请求，返回 `{ok, model, latency_ms, error}` |
| `POST /api/ask` / `.../stream` | body 可带 `llm: {base_url, api_key, model}`（均可选） |

## 10. 已知边界

- 中文长实体名（如"聚乙烯吡咯烷酮"）在文献中常以缩写出现，建议问题中使用缩写（PVP）或在 anchored 策略下填写主体锚点
- 非流式接口在思考模式下可能较慢（长思考链），前端默认走流式
- 图扩展为保守策略（仅沿谓词与共享实体），不推断未经 KG 支持的路径
