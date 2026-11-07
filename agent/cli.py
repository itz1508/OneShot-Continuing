"""OneShot CLI — thin host entrypoint for doctor, run, status, resume, verify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.contracts.scanner import ScannerOutcome, ScannerRunInput
from agent.runtime.controller import HostController, Stage, TransitionError


def cmd_doctor(state_root: str = "/tmp/oneshot-state") -> int:
    """Run environment diagnostics."""
    print("OneShot Doctor")
    print("=" * 40)

    import pydantic

    print(f"Pydantic version: {pydantic.__version__}")

    import rfc8785

    print(f"RFC 8785 library: rfc8785 {getattr(rfc8785, '__version__', 'unknown')}")

    import yaml

    print(f"PyYAML version: {yaml.__version__}")

    # Check provider SDKs
    try:
        import openai

        print(f"OpenAI SDK: {openai.__version__} (meta extra available)")
    except ImportError:
        print("OpenAI SDK: not installed (meta extra not available)")

    # Check state root
    sr = Path(state_root)
    if sr.exists():
        print(f"State root: {sr} (exists)")
    else:
        print(f"State root: {sr} (not created yet)")

    # Check scanner capabilities
    controller = HostController(state_root)
    print(f"Scanner capabilities: {controller.scanner.supported_capabilities or 'none registered'}")
    print(f"Providers: {controller.providers.registered_providers}")

    print("\nDoctor: OK")
    return 0


def cmd_run(task_id: str, state_root: str = "/tmp/oneshot-state") -> int:
    """Execute an existing Research task through the registered host, never simulate completion."""
    from mvp.research_host import execute_research
    from mvp.service import MVPError, MVPService

    service = MVPService(state_root)
    state = service.host.get_state(task_id)
    if state is None:
        print(f"Task {task_id}: not found; submit a task with an input artifact first", file=sys.stderr)
        return 1
    if state.current_stage is not Stage.RESEARCH:
        print(
            f"Task {task_id}: no executable runner registered for stage {state.current_stage.value}",
            file=sys.stderr,
        )
        return 1
    try:
        outcome = execute_research(service, task_id)
    except (MVPError, ValueError) as exc:
        print(f"Task {task_id}: Research blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


def cmd_scan(task_id: str, request_file: str, state_root: str = "/tmp/oneshot-state") -> int:
    """Run the API's exact host scanner and print persisted events as JSON lines."""
    from pydantic import ValidationError

    from mvp.service import MVPError, MVPService

    try:
        request = ScannerRunInput.model_validate_json(Path(request_file).read_bytes())
    except (OSError, ValidationError) as exc:
        print(f"Invalid scanner request file: {type(exc).__name__}", file=sys.stderr)
        return 1

    def show(event: dict[str, object]) -> None:
        print(json.dumps(event, sort_keys=True), flush=True)

    try:
        result = MVPService(state_root).scan_candidate(task_id, request, on_event=show)
    except (MVPError, TransitionError) as exc:
        print(f"Scanner blocked: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"type": "scanner_result", "result": result.model_dump(mode="json")}, sort_keys=True))
    return 0 if result.outcome is ScannerOutcome.PASS else 2


def cmd_status(task_id: str, state_root: str = "/tmp/oneshot-state") -> int:
    """Show task status."""
    controller = HostController(state_root)
    state = controller.get_state(task_id)
    if state is None:
        print(f"Task {task_id}: not found")
        return 1
    print(json.dumps(state.model_dump(mode="json"), indent=2))
    return 0


def cmd_resume(task_id: str, state_root: str = "/tmp/oneshot-state") -> int:
    """Resume a task from its last checkpoint."""
    controller = HostController(state_root)
    state = controller.get_state(task_id)
    if state is None:
        print(f"Task {task_id}: no checkpoint found")
        return 1
    print(f"Task {task_id} resumed at stage: {state.current_stage}")
    print(f"Completed stages: {state.completed_stages}")
    return 0


def cmd_verify(task_id: str, state_root: str = "/tmp/oneshot-state") -> int:
    """Verify task completion."""
    controller = HostController(state_root)
    state = controller.get_state(task_id)
    if state is None:
        print(f"Task {task_id}: not found")
        return 1
    if state.current_stage == Stage.BUILD_VALIDATION and Stage.BUILD_VALIDATION in state.completed_stages:
        print(f"Task {task_id}: COMPLETED")
        return 0
    print(f"Task {task_id}: in progress (stage: {state.current_stage})")
    return 1


def main() -> int:
    """Main CLI entrypoint."""
    if len(sys.argv) < 2:
        print("Usage: python -m agent <command> [args]")
        print("Commands: doctor, run <existing-task-id>, scan <task-id> <request.json> [--state-root PATH], status, resume, verify")
        return 1

    cmd = sys.argv[1]

    if cmd == "doctor":
        return cmd_doctor()
    elif cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: python -m agent run <task_id>")
            return 1
        return cmd_run(sys.argv[2])
    elif cmd == "scan":
        from argparse import ArgumentParser

        parser = ArgumentParser(prog="python -m agent scan")
        parser.add_argument("task_id")
        parser.add_argument("request_file")
        parser.add_argument("--state-root", default="/tmp/oneshot-state")
        args = parser.parse_args(sys.argv[2:])
        return cmd_scan(args.task_id, args.request_file, args.state_root)
    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: python -m agent status <task_id>")
            return 1
        return cmd_status(sys.argv[2])
    elif cmd == "resume":
        if len(sys.argv) < 3:
            print("Usage: python -m agent resume <task_id>")
            return 1
        return cmd_resume(sys.argv[2])
    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("Usage: python -m agent verify <task_id>")
            return 1
        return cmd_verify(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
