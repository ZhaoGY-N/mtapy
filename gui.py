#!/usr/bin/env python
"""mtapy GUI receiver launcher."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    print(
        "缺少 PySide6。请使用项目的虚拟环境运行：\n"
        "  .venv/bin/python gui.py\n"
        "或先安装依赖：\n"
        "  .venv/bin/pip install -e \".[gui]\"",
        file=sys.stderr,
    )
    sys.exit(1)

from mtapy_gui.app import main

if __name__ == "__main__":
    sys.exit(main())