"""Compatibility API: one implementation lives in agent.skills.auditor.__main__."""

from agent.skills.auditor.__main__ import (
    main as main,
)

if __name__ == "__main__":
    raise SystemExit(main())
