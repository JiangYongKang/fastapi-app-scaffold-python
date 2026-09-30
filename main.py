"""Development entrypoint: ``python main.py`` / ``uv run uvicorn main:app``."""

from __future__ import annotations

import uvicorn

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
