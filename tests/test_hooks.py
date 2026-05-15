#!/usr/bin/env python3
"""
Тесты для validate_matsim.py.

Запуск:
    python tests/test_hooks.py

Каждый кейс симулирует PreToolUse-payload и проверяет:
- exit code (всегда должен быть 0 — хук не падает)
- наличие/отсутствие permissionDecision=deny
- что в reason упомянуты ожидаемые правила
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "validate_matsim.py"
FIXTURES = REPO_ROOT / "hooks" / "test-fixtures"


def run_hook(payload: dict) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def parse_decision(stdout: str) -> tuple[str | None, str | None]:
    """Вернуть (decision, reason) из stdout хука. (None, None) если хук молчал."""
    if not stdout.strip():
        return None, None
    data = json.loads(stdout)
    hook_out = data.get("hookSpecificOutput", {})
    return hook_out.get("permissionDecision"), hook_out.get("permissionDecisionReason")


def assert_blocked(name: str, payload: dict, must_contain: list[str]) -> bool:
    exit_code, stdout, stderr = run_hook(payload)
    decision, reason = parse_decision(stdout)
    ok = exit_code == 0 and decision == "deny" and all(
        substr.lower() in (reason or "").lower() for substr in must_contain
    )
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        print(f"  exit={exit_code} decision={decision}")
        print(f"  reason={reason!r}")
        print(f"  stderr={stderr!r}")
    return ok


def assert_passed(name: str, payload: dict) -> bool:
    exit_code, stdout, stderr = run_hook(payload)
    decision, reason = parse_decision(stdout)
    ok = exit_code == 0 and decision is None
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        print(f"  exit={exit_code} decision={decision}")
        print(f"  reason={reason!r}")
        print(f"  stderr={stderr!r}")
    return ok


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def main() -> int:
    results = []

    # 1. Плохой config — должен заблокировать с упоминанием Q1 и Q3
    results.append(assert_blocked(
        "Bad config: flowCap mismatch + missing endTime",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "C:/proj/config.xml",
                "content": read_fixture("bad_config.xml"),
            },
        },
        must_contain=["Q1", "Q3", "flowCapacityFactor", "endTime"],
    ))

    # 2. Хороший config — должен пройти молча
    results.append(assert_passed(
        "Good config: all rules satisfied",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "C:/proj/config.xml",
                "content": read_fixture("good_config.xml"),
            },
        },
    ))

    # 3. Плохой network — freespeed в км/ч
    results.append(assert_blocked(
        "Bad network: freespeed in km/h instead of m/s",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "C:/proj/network.xml",
                "content": read_fixture("bad_network_freespeed.xml"),
            },
        },
        must_contain=["N4", "freespeed", "м/с"],
    ))

    # 4. Не-MATSim файл — должен пройти молча
    results.append(assert_passed(
        "Non-MATSim file: README.md",
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "C:/proj/README.md",
                "old_string": "foo",
                "new_string": "bar",
            },
        },
    ))

    print()
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
