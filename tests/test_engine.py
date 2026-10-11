import numpy as np
import pytest

from investidor.config import CostModel, Execution
from investidor.sim.engine import Simulator, cdi_benchmark, run_simulation

ZERO = {k: CostModel(0, 0, 0) for k in ("crypto", "us", "b3")}
EXE = Execution(min_order_brl=10.0, rebalance_threshold=0.05, max_positions=3, min_cash=0.02)


def weights(panel, **w):
    W = np.zeros((panel.T, panel.N))
    for a, v in w.items():
        W[:, panel.col(a)] = v
    return W


def test_buy_and_hold_zero_cost_equals_price_ratio(panel):
    W = weights(panel, BTC=1.0)
    r = run_simulation(panel, W, EXE, ZERO, 10_000.0, hold_only=True, min_order=1.0)
    j = panel.col("BTC")
    px = panel.close_ff[:, j] * panel.fx[:, j]
    first_fill = r.trades.iloc[0]
    expected = 10_000.0 / (panel.open[1, j] * panel.fx[1, j]) * px[-1]
    assert r.equity.iloc[-1] == pytest.approx(expected, rel=1e-6)
    assert len(r.trades) == 1 and first_fill["side"] == "COMPRA"


def test_cash_never_negative_and_equity_identity(panel, cfg):
    rng = np.random.default_rng(1)
    W = rng.dirichlet(np.ones(panel.N + 1), size=panel.T)[:, :-1]  # pesos aleatórios que somam <= 1
    sim = Simulator(panel, cfg.execution, cfg.costs, 50.0)
    for t in range(1, panel.T):
        sim.step(t, W[t - 1])
        assert sim.cash >= -1e-9
        assert sim.equity_close(t) >= 0
    assert np.all(sim.qty >= 0)  # nunca vendido a descoberto


def test_never_leveraged_even_if_weights_exceed_one(panel, cfg):
    W = np.ones((panel.T, panel.N)) * 5.0  # pesos absurdos
    sim = Simulator(panel, cfg.execution, cfg.costs, 1000.0)
    for t in range(1, 400):
        sim.step(t, W[t - 1])
        invested = sim.equity_close(t) - sim.cash
        assert invested <= sim.equity_close(t) + 1e-6
        assert sim.cash >= -1e-9


def test_round_trip_costs_match_model(tiny_panel, cfg):
    p = tiny_panel
    cm = {"crypto": CostModel(fee_bps=25, spread_bps=10, slippage_bps=5), "us": ZERO["us"], "b3": ZERO["b3"]}
    W = weights(p, BTC=1.0)
    W2 = W.copy(); W2[40:] = 0.0  # compra, depois vende tudo
    r = run_simulation(p, W2, EXE, cm, 1000.0, start_idx=1, end_idx=80, min_order=1.0)
    buys = r.trades[r.trades.side == "COMPRA"].iloc[0]; sells = r.trades[r.trades.side == "VENDA"].iloc[-1]
    assert buys["fill_price_brl"] > buys["price_native"] * buys["fx"]            # compra mais cara que o preço médio
    assert sells["fill_price_brl"] < sells["price_native"] * sells["fx"]         # venda mais barata
    assert buys["fee_brl"] == pytest.approx(buys["notional_brl"] * 25e-4)
    assert r.total_costs > 0


def test_minimum_order_and_lot_step_respected(tiny_panel, cfg):
    p = tiny_panel
    W = weights(p, PETR4=1.0)  # PETR4 tem qty_step = 1
    r = run_simulation(p, W, EXE, ZERO, 1000.0, hold_only=False, min_order=10.0)
    assert (r.trades["qty"] % 1.0 == 0).all()
    # ordem abaixo do mínimo nunca é enviada
    r2 = run_simulation(p, W, EXE, ZERO, 5.0, min_order=10.0)
    assert len(r2.trades) == 0 and r2.equity.iloc[-1] == pytest.approx(5.0)


def test_dividends_credited_to_cash(panel, cfg):
    W = weights(panel, PETR4=1.0)
    r = run_simulation(panel, W, EXE, ZERO, 10_000.0, hold_only=True, min_order=1.0)
    assert r.dividends_received > 0
    j = panel.col("PETR4")
    price_only = r.final_qty["PETR4"] * panel.close_ff[-1, j]
    assert r.equity.iloc[-1] == pytest.approx(price_only + (r.equity.iloc[-1] - price_only), rel=1e-9)
    assert r.equity.iloc[-1] > price_only  # dividendos somam ao patrimônio


def test_liquidate_mode_sells_everything(panel, cfg):
    sim = Simulator(panel, cfg.execution, cfg.costs, 1000.0)
    W = weights(panel, BTC=0.5, SPY=0.4)
    for t in range(1, 30):
        sim.step(t, W[t - 1])
    assert sim.qty.sum() > 0
    sim.mode = "liquidate"
    for t in range(30, 36):
        sim.step(t, W[t - 1])
    assert sim.qty.sum() == 0 and sim.cash > 0


def test_state_roundtrip(panel, cfg):
    sim = Simulator(panel, cfg.execution, cfg.costs, 500.0)
    W = weights(panel, BTC=0.6, GLD=0.3)
    for t in range(1, 40):
        sim.step(t, W[t - 1])
    st = sim.to_state()
    sim2 = Simulator(panel, cfg.execution, cfg.costs, 500.0); sim2.load_state(st)
    for t in range(40, 60):
        a, b = sim.step(t, W[t - 1]), sim2.step(t, W[t - 1])
        assert a == b
    assert sim.cash == pytest.approx(sim2.cash) and np.allclose(sim.qty, sim2.qty)


def test_cdi_benchmark_compounds(panel):
    c = cdi_benchmark(panel, 100.0, 1, 20)
    assert c.iloc[0] == 100.0 and c.iloc[-1] > 100.0 and len(c) == 21
