"""运行配置模块.

配置优先级（高 -> 低）::
    1. 进程环境变量
    2. 工程根目录下的 .env 文件
    3. 代码内默认值

所有配置项统一以 ``KGRAG_`` 前缀暴露，避免与第三方库冲突。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv 为可选依赖：存在则自动加载 .env
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# 工程根目录（src/kgrag/config.py -> 上溯三级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    value = os.environ.get(key, "").strip()
    return value or default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _resolve_path(value: str) -> Path:
    """相对路径一律相对工程根目录解析，保证任意 CWD 下行为一致."""
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    """全局运行配置."""

    # ---- LLM（OpenAI 兼容接口）----
    llm_base_url: str = field(default_factory=lambda: _env("KGRAG_LLM_BASE_URL", "https://api.epicllmrouter.top/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("KGRAG_LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("KGRAG_LLM_MODEL", "deepseek-v4-pro-0813"))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("KGRAG_LLM_TIMEOUT", "180")))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("KGRAG_LLM_MAX_TOKENS", 8192))
    llm_temperature: float = field(default_factory=lambda: float(_env("KGRAG_LLM_TEMPERATURE", "0.2")))
    # 深度思考（reasoning 模型）：关闭后响应更快；复杂机理问题建议开启
    llm_thinking: bool = field(default_factory=lambda: _env("KGRAG_LLM_THINKING", "1") not in ("0", "false", "off"))

    # ---- RAG 索引 ----
    index_dir: Path = field(default_factory=lambda: _resolve_path(_env("KGRAG_INDEX", "../rag_index")))

    # ---- HTTP 服务 ----
    host: str = field(default_factory=lambda: _env("KGRAG_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("KGRAG_PORT", "8600"))
    log_level: str = field(default_factory=lambda: _env("KGRAG_LOG_LEVEL", "INFO"))
    api_key: str = field(default_factory=lambda: _env("KGRAG_API_KEY"))

    # ---- 检索默认参数 ----
    topk: int = field(default_factory=lambda: _env_int("KGRAG_TOPK", "8"))
    window: int = field(default_factory=lambda: _env_int("KGRAG_WINDOW", "1"))

    # ---- 联网学术检索（OpenAlex，目标期刊白名单）----
    web_search_enabled: bool = field(default_factory=lambda: _env("KGRAG_WEB_SEARCH", "1") not in ("0", "false", "off"))
    web_search_timeout_s: float = field(default_factory=lambda: float(_env("KGRAG_WEB_TIMEOUT", "20")))
    web_search_max_results: int = field(default_factory=lambda: _env_int("KGRAG_WEB_MAX", "12"))
    # 综合分析证据总数上限（本地 + 网络）
    evidence_total_cap: int = field(default_factory=lambda: _env_int("KGRAG_EVIDENCE_TOTAL", "20"))

    @property
    def llm_enabled(self) -> bool:
        """LLM 凭据齐备时才启用自然语言生成，否则退化为证据摘录."""
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    """返回全局 Settings 单例（首次调用时冻结，测试可用 ``reset_settings`` 重置）."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS


def reset_settings() -> None:
    """重置配置单例（主要用于测试）."""
    global _SETTINGS
    _SETTINGS = None
