"""kgrag — 电镀领域证据优先的 KG+RAG 问答系统.

分层结构::

    config      运行配置（环境变量 / .env）
    schemas     领域数据模型（Evidence、检索命中、问答请求/响应）
    textproc    中英混合分词与停用词
    kgio        KG CSV（documents/evidence/facts/...）读取
    index       索引构建与加载（BM25 倒排索引，JSON 持久化）
    retrieval   检索策略（词法 BM25、KG 增强、图扩展、流水线编排）
    generation  生成模块（OpenAI 兼容 LLM 客户端、提示词）
    service     问答编排服务（检索 -> 生成 -> 引用）
    api         FastAPI 应用（REST + SSE 流式 + 静态前端）
"""

__version__ = "1.0.0"
