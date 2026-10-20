"""便捷启动脚本：无需 pip install，直接以开发模式运行服务."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kgrag.api.app import main  # noqa: E402

if __name__ == "__main__":
    main()
