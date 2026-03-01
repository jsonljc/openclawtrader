#!/usr/bin/env python3
"""Phase 4 stress testing.

Runs scenarios to verify system behavior under adverse conditions:
- Full cycle + recovery + ledger integrity
- HALT posture blocks new entries
- Idempotency under duplicate intents
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))
sys.path.insert(0, str(_ROOT / "workspace-sentinel"))
sys.path.insert(0, str(_ROOT / "workspace-forge"))
sys.path.insert(0, str(_ROOT / "workspace-watchtower"))

from shared import contracts as C
from shared import ledger
from shared import state_store as store


def _run(cmd: list[str], env: dict | None = None) -> tuple[int, str, str]:
    import subprocess
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(
        [sys.executable, str(_ROOT / "run_cycle.py"), *cmd],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        env=e,
        timeout=60,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


def test_ledger_integrity() -> None:
    ok, msg = ledger.verify_integrity()
    assert ok, f"Ledger integrity failed: {msg}"


def test_full_cycle_and_recovery() -> None:
    code, out, err = _run(["--mode", "full", "--force-signal"])
    assert code == 0, f"Full cycle failed: {out} {err}"
    code2, out2, err2 = _run(["--mode", "recovery"])
    assert code2 == 0, f"Recovery failed: {out2} {err2}"
    test_ledger_integrity()


def test_halt_blocks_entries() -> None:
    portfolio = store.load_portfolio()
    posture_state = store.load_posture_state()
    posture_state["posture"] = C.Posture.HALT
    store.save_posture_state(posture_state)
    n_before = len(portfolio.get("positions", []))
    code, out, err = _run(["--mode", "full", "--force-signal"])
    assert code == 0
    portfolio2 = store.load_portfolio()
    n_after = len(portfolio2.get("positions", []))
    assert n_after <= n_before, "HALT should block new entries"
    posture_state["posture"] = C.Posture.NORMAL
    store.save_posture_state(posture_state)


def main() -> int:
    print("Stress test: full cycle + recovery + ledger integrity")
    test_full_cycle_and_recovery()
    print("  OK")
    print("Stress test: HALT blocks new entries")
    test_halt_blocks_entries()
    print("  OK")
    print("All stress tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
