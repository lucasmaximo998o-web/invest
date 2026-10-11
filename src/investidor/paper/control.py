"""Controle da simulação: iniciar, pausar, retomar e interromper (botões do painel).

Estados:  running (opera)  |  paused (só marca a mercado; mantém posições)  |
          stopped (liquida tudo na próxima abertura e encerra a rodada).
`start` depois de `stopped` abre uma NOVA rodada com capital fictício novo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .ledger import read_json, write_json

ACTIONS = ("start", "pause", "resume", "stop")
STATES = ("running", "paused", "stopped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_control(state_dir: Path) -> dict:
    c = read_json(state_dir / "control.json")
    if c is None:
        c = {"state": "running", "new_run": True, "updated_at": _now(), "updated_by": "sistema (primeiro ciclo)",
             "history": []}
    return c


def apply_action(state_dir: Path, action: str, actor: str = "desconhecido") -> dict:
    if action not in ACTIONS:
        raise ValueError(f"ação inválida '{action}'. Use: {', '.join(ACTIONS)}")
    c = load_control(state_dir)
    before = c["state"]
    if action == "pause" and before == "running":
        c["state"] = "paused"
    elif action in ("resume", "start") and before == "paused":
        c["state"] = "running"
    elif action == "start" and before == "stopped":
        c["state"] = "running"
        c["new_run"] = True
    elif action == "stop" and before in ("running", "paused"):
        c["state"] = "stopped"
        c["new_run"] = False
    # demais combinações são no-ops (ex.: pausar o que já está pausado)
    if c["state"] != before:
        c["updated_at"] = _now()
        c["updated_by"] = actor
        c.setdefault("history", []).append({"at": c["updated_at"], "by": actor, "action": action,
                                            "from": before, "to": c["state"]})
        c["history"] = c["history"][-30:]
    write_json(state_dir / "control.json", c)
    return c
