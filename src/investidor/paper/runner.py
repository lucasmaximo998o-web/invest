"""Paper trading: carteiras fictícias, uma por estratégia, processadas dia a dia.

Cada carteira começa com `paper_initial_brl` FICTÍCIOS. O estado é incremental e as
operações já registradas nunca são reescritas. Usa o MESMO Simulator do backtest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import Config
from ..data.panel import Panel
from ..sim.engine import Simulator
from ..strategies.base import Strategy
from .ledger import append_equity, append_trades, read_json, write_json


def _new_run_id(date_str: str, prior: list[str]) -> str:
    base = "R" + date_str.replace("-", "")
    rid, n = base, 1
    while rid in prior:
        n += 1
        rid = f"{base}-{n}"
    return rid


def _positions(sim: Simulator, panel: Panel, t: int) -> list[dict]:
    px = np.nan_to_num(panel.close_ff[t] * panel.fx[t])
    out = []
    for j in np.flatnonzero(sim.qty > 0):
        out.append({"asset": panel.specs[j].id, "qty": float(sim.qty[j]), "price_brl": float(px[j]),
                    "value_brl": float(sim.qty[j] * px[j])})
    return out


class PaperRunner:
    def __init__(self, cfg: Config, panel: Panel, strategies: dict[str, Strategy],
                 weights: dict[str, np.ndarray], state_dir: Path):
        self.cfg, self.panel, self.strategies, self.weights = cfg, panel, strategies, weights
        self.dir = state_dir
        self.paper = read_json(state_dir / "paper.json", {"version": 1, "active": False, "portfolios": {},
                                                          "closed_runs": []})
        self.events: list[dict] = []  # eventos para alertas (halt, gap de dados...)
        self.new_trades: list[dict] = []
        self.new_equity: list[dict] = []

    # ------------------------------------------------------------------ run lifecycle
    def _start_run(self, as_of_idx: int) -> None:
        date_str = str(self.panel.dates[as_of_idx].date())
        prior = [r["run_id"] for r in self.paper.get("closed_runs", [])]
        if self.paper.get("run_id"):
            prior.append(self.paper["run_id"])
        run_id = _new_run_id(date_str, prior)
        self.paper.update({"active": True, "run_id": run_id, "start_date": date_str,
                           "initial": self.cfg.paper_initial,
                           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "portfolios": {}})
        for sid, s in self.strategies.items():
            if not s.paper_ok:
                continue
            sim = Simulator(self.panel, self.cfg.execution, self.cfg.costs, self.cfg.paper_initial,
                            hold_only=s.hold_only)
            self.paper["portfolios"][sid] = {
                "status": "active", "last_date": date_str, "peak": self.cfg.paper_initial,
                "sim": sim.to_state(), "halt_reason": None, "risk_managed": s.family != "passiva",
                "alerted_dd": [], "positions": [],
            }
            self.new_equity.append({
                "date": date_str, "run_id": run_id, "portfolio": sid, "equity": self.cfg.paper_initial,
                "cash": self.cfg.paper_initial, "exposure": 0.0, "drawdown": 0.0, "status": "active"})
        self.events.append({"kind": "RUN_STARTED", "severity": "info",
                            "message": f"Nova simulação {run_id} iniciada em {date_str} com R$ "
                                       f"{self.cfg.paper_initial:.2f} fictícios por carteira."})

    def _close_run(self, reason: str) -> None:
        summary = {sid: {"status": p["status"], "final_equity": p.get("final_equity")}
                   for sid, p in self.paper["portfolios"].items()}
        self.paper.setdefault("closed_runs", []).append({
            "run_id": self.paper["run_id"], "start_date": self.paper.get("start_date"),
            "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": reason, "summary": summary})
        self.paper["active"] = False

    # ------------------------------------------------------------------ main
    def process(self, control: dict, as_of_idx: int) -> None:
        state = control["state"]
        if control.get("new_run") and state == "running":
            self._start_run(as_of_idx)
            control["new_run"] = False
        elif not self.paper.get("active"):
            return  # parado/sem rodada: nada a simular
        run_id = self.paper["run_id"]

        if state == "stopped":
            for p in self.paper["portfolios"].values():
                if p["status"] in ("active", "liquidating"):
                    p["status"] = "liquidating"
                    p["sim"]["mode"] = "liquidate"
                    p["halt_reason"] = p.get("halt_reason") or "interrompida pelo usuário"

        for sid, port in self.paper["portfolios"].items():
            self._process_portfolio(sid, port, run_id, as_of_idx, paused=(state == "paused"))

        if state == "stopped" and all(p["status"] in ("closed", "halted") for p in self.paper["portfolios"].values()):
            self._close_run("interrompida pelo usuário")

    def _process_portfolio(self, sid: str, port: dict, run_id: str, as_of_idx: int, paused: bool) -> None:
        panel, cfg = self.panel, self.cfg
        last_idx = panel.index_of(port["last_date"])
        if last_idx >= as_of_idx:
            return
        held = set(port["sim"]["qty"])
        missing = held - set(panel.ids)
        if missing:
            self.events.append({"kind": "DATA_GAP", "severity": "critical", "portfolio": sid,
                                "message": f"Carteira {sid} não atualizada: sem dados de {sorted(missing)} "
                                           f"(posições abertas)."})
            return
        sim = Simulator(panel, cfg.execution, cfg.costs, port["sim"]["initial"],
                        hold_only=self.strategies[sid].hold_only)
        sim.load_state(port["sim"])
        W = self.weights[sid]
        for t in range(last_idx + 1, as_of_idx + 1):
            date_str = str(panel.dates[t].date())
            status = port["status"]
            if status in ("halted", "closed"):
                trades = []
                sim.accrue_dividends(t)
            elif paused and status == "active":
                trades = []
                sim.accrue_dividends(t)
            else:
                trades = sim.step(t, W[t - 1])
            for tr in trades:
                self.new_trades.append({**tr, "run_id": run_id, "portfolio": sid})
            eq = sim.equity_close(t)
            port["peak"] = max(port["peak"], eq)
            dd = eq / port["peak"] - 1.0
            if port["status"] == "active" and port["risk_managed"] and dd <= -cfg.risk.max_drawdown_halt:
                port["status"] = "liquidating"
                port["halt_reason"] = (f"drawdown de {dd:.1%} atingiu o limite de "
                                       f"{cfg.risk.max_drawdown_halt:.0%} em {date_str}")
                sim.mode = "liquidate"
                self.events.append({"kind": "HALT", "severity": "critical", "portfolio": sid,
                                    "message": f"Carteira {sid} INTERROMPIDA: {port['halt_reason']}. "
                                               "Posições serão liquidadas na próxima abertura."})
            if port["status"] == "liquidating" and not np.any(sim.qty > 0):
                port["status"] = "halted" if "drawdown" in (port["halt_reason"] or "") else "closed"
            expo = 0.0 if eq <= 0 else (eq - sim.cash) / eq
            self.new_equity.append({"date": date_str, "run_id": run_id, "portfolio": sid, "equity": round(eq, 6),
                                    "cash": round(sim.cash, 6), "exposure": round(expo, 6),
                                    "drawdown": round(dd, 6), "status": ("paused" if paused and port["status"] == "active" else port["status"])})
            port["last_date"] = date_str
            port["final_equity"] = eq
        port["sim"] = sim.to_state()
        port["positions"] = _positions(sim, panel, as_of_idx)

    # ------------------------------------------------------------------ persistência
    def save(self) -> None:
        # ordem determinística (data, ordem das carteiras): o livro-razão fica idêntico
        # independentemente de quantos dias foram processados por ciclo
        order = {sid: i for i, sid in enumerate(self.paper.get("portfolios", {}))}
        self.new_trades.sort(key=lambda r: (r["date"], order.get(r["portfolio"], 0)))
        self.new_equity.sort(key=lambda r: (r["date"], order.get(r["portfolio"], 0)))
        append_trades(self.dir / "trades.csv", self.new_trades)
        append_equity(self.dir / "equity.csv", self.new_equity)
        write_json(self.dir / "paper.json", self.paper)
