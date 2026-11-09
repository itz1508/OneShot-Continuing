"""Host command entry: reuse the existing OneShot CLI."""

from agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
