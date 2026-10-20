# RAG 上线检查清单

## 已完成

- [x] 本地证据索引
- [x] BM25 检索（jieba 词级分词，k1=1.2 b=0.75）
- [x] KG-aware 加权（hit@5 +2.15 pp，hit@10 +3.0 pp）
- [x] BGE dense 基线（bge-small-zh-v1.5，含完整评测）
- [x] RRF 混合与 dense rerank 基线（含完整评测）
- [x] 检索层消融：lexical vs KG-aware，k=5/k=10，按关系切片
- [x] evidence_id / doc_id 溯源
- [x] 评测集自动构建（回归集 + 困难集 + 负例探针）
- [x] 评测集 provenance 校验（validate_eval.py）
- [x] FastAPI `/health`、`/ask`、`/metrics`
- [x] 可选 API key
- [x] 基于 IP 的内存限流
- [x] 异常响应不泄露内部错误
- [x] 未知材料/领域 yes-no 查询的保守拒答 guard
- [x] 索引版本和源 CSV hash

## 上线前必须完成

- [ ] 人工审核 gold 评测集；当前自动集只是 silver
- [ ] 证据窗口化（段落/表格/图注），当前为单行
- [ ] 事实结构化（subject/predicate/object/qualifiers）补齐 KG
- [ ] Neo4j 路径检索和原文 evidence backtracking
- [x] 保守 CSV 图证据扩展（仅共享实体/关系，不推断路径）
- [ ] 证据充分性判定，不以“检索到结果”代替“可回答”
- [ ] 无答案、冲突、否定、时间和实验条件测试（当前仅 4 条探针）
- [ ] 答案级评测：正确性、条件保留、引用蕴含、unsupported claim rate
- [ ] API key 改为外部认证系统或网关认证
- [ ] Redis/网关限流，替代单进程内存限流
- [ ] TLS、CORS、请求体大小和超时策略
- [ ] 结构化日志、指标后端、告警和 trace id
- [ ] 索引热更新/回滚和 schema 兼容检查
- [ ] 并发、压力、故障恢复和备份测试
- [ ] 权限隔离和文献许可审查

## 当前结论

当前版本适合内部研究服务和离线回归。检索层已完成系统对比（BM25/KG-aware/BGE dense/RRF hybrid/rerank），当前最优形态为 jieba+BM25+KG-aware boost；dense 基线已具备完整代码但按当前证据形态（单行、模板问题）不占优，留待证据窗口化与真实用户问题积累后重测。答案级评测与人工 gold 集是上线前的主要缺口。
