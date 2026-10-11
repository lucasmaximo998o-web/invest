"""Alertas de perdas, mudanças importantes e falhas. Registro em alerts.jsonl + push opcional (ntfy)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import numpy as np
import requests

from .config import Config
from .data.panel import Panel
from .data.store import MarketData

log = logging.getLogger("investidor.alerts")
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make(kind: str, severity: str, message: str, date: str, portfolio: str | None = None,
         key: str | None = None) -> dict:
    return {"id": key or f"{kind}:{portfolio or '-'}:{date}", "ts": _now(), "date": date, "kind": kind,
            "severity": severity, "portfolio": portfolio, "message": message}


def evaluate(cfg: Config, paper: dict, runner_events: list[dict], new_equity: list[dict], md: MarketData,
             panel: Panel, as_of_idx: int, existing_ids: set[str]) -> list[dict]:
    """Gera alertas NOVOS (sem repetir os já registrados)."""
    date = str(panel.dates[as_of_idx].date())
    out: list[dict] = []
    primary = cfg.primary_strategy
    run_id = paper.get("run_id", "-")

    for ev in runner_events:
        out.append(make(ev["kind"], ev["severity"], ev["message"], date, ev.get("portfolio"),
                        key=f"{ev['kind']}:{ev.get('portfolio') or '-'}:{run_id}:{date}"))

    # --- perdas: drawdown por níveis e perda diária
    by_port: dict[str, list[dict]] = {}
    for r in new_equity:
        by_port.setdefault(r["portfolio"], []).append(r)
    for sid, rows in by_port.items():
        port = paper.get("portfolios", {}).get(sid)
        if not port or not port.get("risk_managed"):
            continue
        rows = sorted(rows, key=lambda r: r["date"])
        dd = float(rows[-1]["drawdown"])
        crossed = [L for L in cfg.risk.drawdown_alert_levels if dd <= -L]
        alerted = list(port.get("alerted_dd", []))
        new = [L for L in crossed if L not in alerted]
        port["alerted_dd"] = [L for L in alerted if dd <= -L / 2] + new
        if new:
            lvl = max(new)
            sev = "warning" if sid == primary else "info"
            out.append(make("DRAWDOWN", sev, f"{sid}: drawdown de {dd:.1%} (nível {lvl:.0%} ultrapassado). "
                            "Simulação com dinheiro fictício.", date, sid, key=f"DD{lvl}:{sid}:{run_id}:{date}"))
        if len(rows) >= 2:
            prev, cur = float(rows[-2]["equity"]), float(rows[-1]["equity"])
            if prev > 0 and cur / prev - 1 <= -cfg.risk.daily_loss_alert:
                sev = "warning" if sid == primary else "info"
                out.append(make("PERDA_DIARIA", sev, f"{sid}: perda de {cur / prev - 1:.1%} em um dia.", date, sid))

    # --- movimentos extremos de ativos (mudança importante de mercado)
    c = panel.close_ff
    if as_of_idx >= 1:
        for j, spec in enumerate(panel.specs):
            a, b = c[as_of_idx - 1, j], c[as_of_idx, j]
            if np.isfinite(a) and np.isfinite(b) and a > 0 and abs(b / a - 1) >= cfg.risk.asset_move_alert:
                out.append(make("MOVIMENTO_ATIVO", "warning",
                                f"{spec.id} variou {b / a - 1:+.1%} em 1 dia ({date}).", date, None,
                                key=f"MOV:{spec.id}:{date}"))

    # --- qualidade dos dados
    for s in md.skipped:
        if "BRAPI_TOKEN" in s["reason"]:
            continue
        out.append(make("DADOS_EXCLUIDOS", "warning", f"{s['asset']} fora do ciclo: {s['reason']}", date, None,
                        key=f"DATA:{s['asset']}:{date}"))
    for n in md.notes:
        out.append(make("DADOS_AVISO", "warning", n, date, None, key=f"NOTE:{n[:40]}:{date}"))
    cc = md.crosscheck or {}
    if cc.get("ok") is False:
        out.append(make("CHECAGEM_CRUZADA", "warning", "Preços de cripto divergem entre Binance e CoinGecko.",
                        date, None, key=f"XCHK:{date}"))
    return [a for a in out if a["id"] not in existing_ids]


def notify(alerts: list[dict]) -> int:
    """Push opcional via ntfy.sh (app Android gratuito, sem conta). Só warning/critical."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return 0
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    sent = 0
    for a in alerts:
        if SEVERITY_ORDER.get(a["severity"], 0) < 1:
            continue
        try:
            r = requests.post(f"{server}/{topic}", data=a["message"].encode("utf-8"), timeout=15, headers={
                "Title": "INVESTIDOR AI - " + a["kind"], "Priority": "5" if a["severity"] == "critical" else "3",
                "Tags": "rotating_light" if a["severity"] == "critical" else "warning"})
            sent += int(r.ok)
        except requests.RequestException as exc:  # nunca derruba o ciclo
            log.warning("falha ao enviar notificação: %s", exc)
    return sent
