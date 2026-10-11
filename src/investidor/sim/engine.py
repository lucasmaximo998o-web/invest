"""Motor de execução simulada - usado IGUAL no backtest e no paper trading.

Semântica temporal (sem look-ahead):
  * os pesos-alvo W[t-1] são decididos com dados até o FECHAMENTO de t-1;
  * são executados na ABERTURA de t, ao preço de abertura +- (meio spread + derrapagem),
    mais taxas; ativos sem pregão em t esperam o próximo dia com pregão;
  * a marcação a mercado de t usa o fechamento de t.

Restrições realistas: sem alavancagem (caixa nunca negativo), sem venda a descoberto,
lote mínimo (qty_step), ordem mínima em R$, banda de rebalanceamento (reduz giro).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import CostModel, Execution
from ..data.panel import Panel


def _floor_step(x: np.ndarray, step: np.ndarray) -> np.ndarray:
    return np.round(np.floor(x / step + 1e-9) * step, 10)


class Simulator:
    def __init__(self, panel: Panel, execution: Execution, costs: dict[str, CostModel],
                 initial: float, hold_only: bool = False, min_order: float | None = None):
        self.p = panel
        self.N = panel.N
        self.slip = np.array([costs[s.klass].slip_bps for s in panel.specs]) / 1e4
        self.buy_fee = np.array([costs[s.klass].buy_fee_bps for s in panel.specs]) / 1e4
        self.sell_fee = np.array([costs[s.klass].sell_fee_bps for s in panel.specs]) / 1e4
        self.step_q = np.array([s.qty_step for s in panel.specs], dtype=float)
        self.min_order = float(execution.min_order_brl if min_order is None else min_order)
        self.thr = execution.rebalance_threshold
        self.hold_only = hold_only
        self.initial = float(initial)
        self.cash = float(initial)
        self.qty = np.zeros(self.N)
        self.bought = np.zeros(self.N, dtype=bool)
        self.mode = "run"  # run | liquidate
        self.fees_paid = 0.0
        self.slippage_paid = 0.0
        self.notional_traded = 0.0
        self.dividends_received = 0.0

    # ------------------------------------------------------------------ valores
    def equity_close(self, t: int) -> float:
        px = np.nan_to_num(self.p.close_ff[t] * self.p.fx[t])
        return float(self.cash + np.sum(self.qty * px))

    def positions_value(self, t: int) -> np.ndarray:
        return self.qty * np.nan_to_num(self.p.close_ff[t] * self.p.fx[t])

    def accrue_dividends(self, t: int) -> None:
        """Proventos em dinheiro creditados na data ex (simplificação: sem defasagem de pagamento)."""
        div = self.p.div[t]
        if np.any(div > 0) and np.any(self.qty > 0):
            got = float(np.sum(self.qty * div * self.p.fx[t]))
            self.cash += got
            self.dividends_received += got

    # ------------------------------------------------------------------ passo diário
    def step(self, t: int, w: np.ndarray, reason: str = "sinal da estratégia") -> list[dict]:
        p = self.p
        trades: list[dict] = []
        self.accrue_dividends(t)

        tradable = p.tradable[t]
        open_nat = p.open[t]
        prev_close = p.close_ff[t - 1] if t > 0 else p.close_ff[t]
        px_val = np.where(tradable, open_nat, prev_close) * p.fx[t]
        px_val = np.nan_to_num(px_val)
        equity_open = self.cash + float(np.sum(self.qty * px_val))

        w = np.nan_to_num(np.asarray(w, dtype=float), nan=0.0)
        w = np.clip(w, 0.0, 1.0)
        if self.mode == "liquidate":
            w = np.zeros(self.N)
        s = w.sum()
        if s > 1.0:
            w = w / s

        px_fill_buy = np.where(tradable, open_nat * (1 + self.slip) * p.fx[t], np.nan)
        px_fill_sell = np.where(tradable, open_nat * (1 - self.slip) * p.fx[t], np.nan)

        if self.hold_only and self.mode != "liquidate":
            self._hold_only_buys(t, w, px_fill_buy, open_nat, trades, reason)
        else:
            self._rebalance(t, w, equity_open, px_val, px_fill_buy, px_fill_sell, open_nat, trades, reason)
        if self.cash < -1e-6:  # invariante: sem saldo negativo, sem alavancagem
            raise AssertionError(f"caixa negativo em {p.dates[t].date()}: {self.cash}")
        self.cash = max(self.cash, 0.0)
        return trades

    # ------------------------------------------------------------------ internals
    def _record(self, t: int, i: int, side: str, qty: float, px_fill: float, open_nat: float,
                fee: float, reason: str, trades: list[dict]) -> None:
        p = self.p
        notional = qty * px_fill
        mid = open_nat * p.fx[t, i]
        slip_cost = abs(px_fill - mid) * qty
        self.fees_paid += fee
        self.slippage_paid += slip_cost
        self.notional_traded += notional
        trades.append({
            "date": str(p.dates[t].date()), "asset": p.specs[i].id, "side": side,
            "qty": float(qty), "price_native": float(open_nat), "fx": float(p.fx[t, i]),
            "fill_price_brl": float(px_fill), "notional_brl": float(notional),
            "fee_brl": float(fee), "slippage_brl": float(slip_cost), "reason": reason,
        })

    def _buy(self, t, i, qty, px_buy, open_nat, trades, reason) -> float:
        cost_per = px_buy[i] * (1 + self.buy_fee[i])
        max_qty = _floor_step(np.array([max(self.cash, 0.0) / cost_per]), self.step_q[i:i + 1])[0]
        q = min(qty, max_qty)
        if q <= 0 or q * px_buy[i] < self.min_order - 1e-9:
            return 0.0
        notional = q * px_buy[i]
        fee = notional * self.buy_fee[i]
        self.cash -= notional + fee
        self.qty[i] += q
        self._record(t, i, "COMPRA", q, px_buy[i], open_nat[i], fee, reason, trades)
        return q

    def _sell(self, t, i, qty, px_sell, open_nat, trades, reason) -> None:
        qty = min(qty, self.qty[i])
        if qty <= 0:
            return
        notional = qty * px_sell[i]
        fee = notional * self.sell_fee[i]
        self.cash += notional - fee
        self.qty[i] -= qty
        if self.qty[i] < 1e-12:
            self.qty[i] = 0.0
        self._record(t, i, "VENDA", qty, px_sell[i], open_nat[i], fee, reason, trades)

    def _hold_only_buys(self, t, w, px_buy, open_nat, trades, reason) -> None:
        for i in np.where((w > 0) & ~self.bought & self.p.tradable[t])[0]:
            target_value = w[i] * self.initial
            q = _floor_step(np.array([target_value / (px_buy[i] * (1 + self.buy_fee[i]))]),
                            self.step_q[i:i + 1])[0]
            self._buy(t, i, q, px_buy, open_nat, trades, "compra inicial (comprar e segurar)")
            self.bought[i] = True

    def _rebalance(self, t, w, equity_open, px_val, px_buy, px_sell, open_nat, trades, reason) -> None:
        tradable = self.p.tradable[t]
        target_value = w * equity_open
        with np.errstate(invalid="ignore", divide="ignore"):
            tq = np.where(px_val > 0, _floor_step(target_value / np.where(px_val > 0, px_val, 1.0), self.step_q), 0.0)
        delta = tq - self.qty
        band = max(self.min_order, self.thr * equity_open)
        sells, buys = [], []
        for i in np.where(tradable & (np.abs(delta) > 1e-12))[0]:
            value = abs(delta[i]) * px_val[i]
            if delta[i] < 0:
                full_exit = tq[i] <= 0
                if full_exit or value >= band:
                    sells.append(i)
            else:
                needed = self.min_order if self.qty[i] == 0 else band
                if value >= needed:
                    buys.append(i)
        for i in sells:
            self._sell(t, i, -delta[i] if tq[i] > 0 else self.qty[i], px_sell, open_nat, trades, reason)
        for i in sorted(buys, key=lambda k: -delta[k] * px_val[k]):
            self._buy(t, i, delta[i], px_buy, open_nat, trades, reason)

    # ------------------------------------------------------------------ estado (paper)
    def to_state(self) -> dict:
        return {
            "cash": self.cash, "qty": {s.id: float(q) for s, q in zip(self.p.specs, self.qty) if q > 0},
            "bought": [s.id for s, b in zip(self.p.specs, self.bought) if b],
            "initial": self.initial, "mode": self.mode, "fees_paid": self.fees_paid,
            "slippage_paid": self.slippage_paid, "notional_traded": self.notional_traded,
            "dividends_received": self.dividends_received,
        }

    def load_state(self, st: dict) -> None:
        self.cash = float(st["cash"])
        self.qty = np.zeros(self.N)
        ids = self.p.ids
        for k, v in st.get("qty", {}).items():
            if k in ids:
                self.qty[ids.index(k)] = float(v)
        self.bought = np.zeros(self.N, dtype=bool)
        for k in st.get("bought", []):
            if k in ids:
                self.bought[ids.index(k)] = True
        self.initial = float(st["initial"])
        self.mode = st.get("mode", "run")
        self.fees_paid = float(st.get("fees_paid", 0))
        self.slippage_paid = float(st.get("slippage_paid", 0))
        self.notional_traded = float(st.get("notional_traded", 0))
        self.dividends_received = float(st.get("dividends_received", 0))


@dataclass
class SimResult:
    equity: pd.Series  # patrimônio em R$ (diário, inclui o ponto inicial)
    exposure: pd.Series  # fração investida
    trades: pd.DataFrame
    fees_paid: float
    slippage_paid: float
    notional_traded: float
    dividends_received: float
    final_qty: dict = field(default_factory=dict)

    @property
    def total_costs(self) -> float:
        return self.fees_paid + self.slippage_paid


def run_simulation(panel: Panel, weights: np.ndarray, execution: Execution, costs: dict[str, CostModel],
                   initial: float, start_idx: int = 1, end_idx: int | None = None,
                   hold_only: bool = False, min_order: float | None = None) -> SimResult:
    """Simula do dia `start_idx` ao `end_idx` (inclusive). O dia start_idx executa W[start_idx-1]."""
    end_idx = panel.T - 1 if end_idx is None else end_idx
    start_idx = max(start_idx, 1)
    sim = Simulator(panel, execution, costs, initial, hold_only=hold_only, min_order=min_order)
    idx = [start_idx - 1]
    eq = [float(initial)]
    expo = [0.0]
    all_trades: list[dict] = []
    for t in range(start_idx, end_idx + 1):
        all_trades.extend(sim.step(t, weights[t - 1]))
        e = sim.equity_close(t)
        idx.append(t)
        eq.append(e)
        expo.append(0.0 if e <= 0 else (e - sim.cash) / e)
    dates = panel.dates[idx]
    cols = ["date", "asset", "side", "qty", "price_native", "fx", "fill_price_brl", "notional_brl",
            "fee_brl", "slippage_brl", "reason"]
    return SimResult(
        equity=pd.Series(eq, index=dates, name="equity"),
        exposure=pd.Series(expo, index=dates, name="exposure"),
        trades=pd.DataFrame(all_trades, columns=cols),
        fees_paid=sim.fees_paid, slippage_paid=sim.slippage_paid,
        notional_traded=sim.notional_traded, dividends_received=sim.dividends_received,
        final_qty={s.id: float(q) for s, q in zip(panel.specs, sim.qty) if q > 0},
    )


def cdi_benchmark(panel: Panel, initial: float, start_idx: int = 1, end_idx: int | None = None) -> pd.Series:
    """100% do CDI, bruto de impostos (referência de renda fixa)."""
    end_idx = panel.T - 1 if end_idx is None else end_idx
    start_idx = max(start_idx, 1)
    rf = panel.rf[start_idx:end_idx + 1]
    eq = initial * np.concatenate([[1.0], np.cumprod(1.0 + rf)])
    return pd.Series(eq, index=panel.dates[start_idx - 1:end_idx + 1], name="cdi")
