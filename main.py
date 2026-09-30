"""模板入口：保留开箱即用行为。

直接运行：python main.py
ASGI 入口：main:app
"""

from __future__ import annotations

import uvicorn

from app.application import create_app

app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
