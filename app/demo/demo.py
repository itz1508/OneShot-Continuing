"""Local demo ASGI app: existing API and web/public/live.html on one origin."""

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from mvp.api import app

app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "web" / "public", html=True), name="web")
