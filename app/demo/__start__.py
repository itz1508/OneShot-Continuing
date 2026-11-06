"""Start the local OneShot demo without Modal or a separate web server."""

from __future__ import annotations

import uvicorn


def start() -> None:
    """Serve the demo ASGI app on the local loopback interface."""
    uvicorn.run("app.demo.demo:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    start()
