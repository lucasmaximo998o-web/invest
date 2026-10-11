"""Viabilidade prática de operar com pouco capital (ex.: R$ 50) e porta de liberação para dinheiro real.

Nada aqui envia ordens. O "go-live gate" apenas AVALIA critérios objetivos; operar com dinheiro real
exige implementação nova e autorização expressa do titular (docs/INTEGRACAO_REAL.md).
"""
from __future__ import annotations

import math

import numpy as np

from .config import Config
from .data.panel import Panel


def asset_feasibility(cfg: Config, panel: Panel, capital: float) -> list[dict]:
    k = cfg.execution.max_positions
    pos_value = capital * (1 - cfg.execution.min_cash) / k
    out = []
    for j, spec in enumerate(panel.specs):
        price = float(panel.close_ff[-1, j] * panel.fx[-1, j])
        cm = cfg.costs[spec.klass]
        qty = math.floor(pos_value / price / spec.qty_step + 1e-9) * spec.qty_step if price > 0 else 0.0
        cost_value = qty * price
        bars = panel.bars(spec.id).tail(60)
        adv_brl = float((bars["close"] * bars["volume"]).median() * panel.fx[-1, j]) if len(bars) else 0.0
        r = np.log(panel.bars(spec.id)["close"]).diff().tail(90)
        per_year = 365 if spec.klass == "crypto" else 252
        vol = float(r.std(ddof=1) * math.sqrt(per_year)) if len(r) > 20 else None
        feasible = qty > 0 and cost_value >= cfg.execution.min_order_brl
        if not feasible:
            note = (f"1 unidade custa R$ {price:,.2f} e a posição-alvo é R$ {pos_value:,.2f}: "
                    "não cabe no capital").replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            note = "ok"
        out.append({
            "asset": spec.id, "name": spec.name, "klass": spec.klass, "price_brl": price,
            "target_position_brl": pos_value, "units_affordable": qty, "feasible": bool(feasible),
            "round_trip_cost_pct": cm.round_trip_bps / 100.0,
            "round_trip_cost_brl": pos_value * cm.round_trip_bps / 1e4,
            "adv_brl_60d": adv_brl, "vol_annual_90d": vol, "note": note,
            "total_return_series": spec.total_return,
        })
    return out


def scenarios(capital: float) -> list[dict]:
    """Ordem de grandeza do que R$ capital pode render (NÃO são previsões)."""
    return [{"label": lbl, "annual_return": r, "final_brl": capital * (1 + r), "pnl_brl": capital * r}
            for lbl, r in (("perda forte", -0.40), ("perda", -0.15), ("zero a zero", 0.0),
                           ("renda fixa ~CDI", 0.10), ("bom ano", 0.30), ("excepcional", 0.80))]


def golive_gate(cfg: Config, primary: dict | None, backtest: dict | None, paper_days: int,
                critical_alerts_30d: int, feas: list[dict]) -> dict:
    """Critérios objetivos para DISCUTIR (não para executar) uma integração real."""
    crit = []

    def add(name: str, ok: bool | None, detail: str, manual: bool = False):
        crit.append({"criterio": name, "ok": ok, "detalhe": detail, "manual": manual})

    add("Pelo menos 180 dias de paper trading contínuo", paper_days >= 180, f"{paper_days} dias")
    if primary:
        s = primary.get("summary", {})
        add("Drawdown máximo do paper abaixo de 20%", abs(s.get("max_drawdown", 0)) < 0.20,
            f"{s.get('max_drawdown', 0):.1%}")
    lb = {r["id"]: r for r in (backtest or {}).get("leaderboard", [])}
    prim = lb.get(cfg.primary_strategy)
    if prim:
        dsr = prim.get("dsr")
        add("Evidência estatística no backtest (DSR >= 0,95)", dsr is not None and dsr >= 0.95,
            f"DSR = {dsr:.2f}" if dsr is not None else "n/d")
    add("Sem alertas críticos de dados/ciclo nos últimos 30 dias", critical_alerts_30d == 0,
        f"{critical_alerts_30d} alertas críticos")
    ok_pos = [f for f in feas if f["feasible"]]
    add("Há ativos viáveis para o capital (ordem mínima e custos)", len(ok_pos) >= 2,
        f"{len(ok_pos)} de {len(feas)} ativos viáveis")
    add("Elegibilidade legal/idade da plataforma verificada", None,
        "VERIFICAÇÃO MANUAL: titular maior de idade, cadastro (KYC) aprovado, regras da plataforma", manual=True)
    add("Autorização EXPRESSA e por escrito do titular", None,
        "PENDENTE - nunca presumida. Sem ela nenhuma integração real é implementada.", manual=True)
    auto = [c for c in crit if not c["manual"]]
    return {
        "criteria": crit,
        "automated_ok": all(c["ok"] for c in auto),
        "eligible_for_discussion": all(c["ok"] for c in auto),
        "live_trading_enabled": False,
        "note": ("Mesmo com todos os critérios automáticos satisfeitos, a operação real continua DESABILITADA: "
                 "exige verificação legal manual, sua autorização expressa e implementação nova."),
    }
