import csv

import numpy as np
import pytest

from investidor.config import Config
from investidor.paper import control as ctl
from investidor.paper.ledger import append_trades, read_trades, verify_ledger
from investidor.paper.runner import PaperRunner
from investidor.sim.engine import run_simulation
from investidor.strategies.base import Ctx
from investidor.strategies.registry import build_strategies


@pytest.fixture()
def env(panel, cfg, tmp_path):
    strategies = {k: v for k, v in build_strategies(cfg).items() if k in ("bh_btc", "dual_momentum", "trend_sma", "lowvol")}
    ctx = Ctx(cfg.execution.max_positions, cfg.execution.min_cash)
    weights = {k: s.weights(panel, ctx) for k, s in strategies.items()}
    return panel, cfg, strategies, weights, tmp_path


def run_days(env, control, upto_idx, runner=None):
    panel, cfg, strategies, weights, tmp = env
    r = PaperRunner(cfg, panel, strategies, weights, tmp)
    r.process(control, upto_idx)
    r.save()
    return r


def test_ledger_hash_chain_detects_tampering(tmp_path):
    p = tmp_path / "trades.csv"
    rows = [{"date": "2026-01-0%d" % i, "run_id": "R1", "portfolio": "x", "asset": "BTC", "side": "COMPRA", "qty": 1,
             "price_native": 1, "fx": 1, "fill_price_brl": 1, "notional_brl": 1, "fee_brl": 0, "slippage_brl": 0, "reason": "t"}
            for i in range(1, 6)]
    append_trades(p, rows[:3]); append_trades(p, rows[3:])
    assert verify_ledger(p)[0]
    txt = p.read_text().replace("2026-01-02", "2026-01-09")
    p.write_text(txt)
    ok, why = verify_ledger(p)
    assert not ok and "linha" in why
    assert all(r["mode"] == "PAPER" for r in read_trades(p))


def test_control_transitions(tmp_path):
    c = ctl.load_control(tmp_path)
    assert c["state"] == "running" and c["new_run"]
    assert ctl.apply_action(tmp_path, "pause", "t")["state"] == "paused"
    assert ctl.apply_action(tmp_path, "pause", "t")["state"] == "paused"  # no-op
    assert ctl.apply_action(tmp_path, "resume", "t")["state"] == "running"
    assert ctl.apply_action(tmp_path, "stop", "t")["state"] == "stopped"
    c = ctl.apply_action(tmp_path, "start", "t")
    assert c["state"] == "running" and c["new_run"] is True
    with pytest.raises(ValueError):
        ctl.apply_action(tmp_path, "sell_everything_now", "t")
    assert len(c["history"]) == 4


def test_paper_matches_backtest_exactly(env):
    panel, cfg, strategies, weights, tmp = env
    start, end = 800, 900
    control = {"state": "running", "new_run": True}
    run_days(env, control, start)        # cria a rodada em `start`
    run_days(env, control, end)          # processa 100 dias de uma vez (catch-up)
    import json
    state = json.load(open(tmp / "paper.json"))
    for sid, s in strategies.items():
        bt = run_simulation(panel, weights[sid], cfg.execution, cfg.costs, cfg.paper_initial,
                            start_idx=start + 1, end_idx=end, hold_only=s.hold_only)
        assert state["portfolios"][sid]["final_equity"] == pytest.approx(bt.equity.iloc[-1], abs=1e-9)


def test_incremental_equals_single_shot(env, tmp_path):
    panel, cfg, strategies, weights, _ = env
    control = {"state": "running", "new_run": True}
    a = (panel, cfg, strategies, weights, tmp_path / "a"); b = (panel, cfg, strategies, weights, tmp_path / "b")
    for d in (a, b):
        d[4].mkdir()
    run_days(a, dict(control), 600)
    for t in range(601, 701):
        run_days(a, {"state": "running", "new_run": False}, t)   # um dia por vez
    run_days(b, dict(control), 600); run_days(b, {"state": "running", "new_run": False}, 700)
    ta = [dict(r) for r in csv.DictReader(open(tmp_path / "a" / "trades.csv"))]
    tb = [dict(r) for r in csv.DictReader(open(tmp_path / "b" / "trades.csv"))]
    assert len(ta) > 5
    assert ta == tb  # linha a linha, inclusive o hash encadeado: ledger independe da cadência dos ciclos
    ea = list(csv.DictReader(open(tmp_path / "a" / "equity.csv"))); eb = list(csv.DictReader(open(tmp_path / "b" / "equity.csv")))
    assert ea == eb


def test_reprocessing_same_day_is_idempotent(env):
    control = {"state": "running", "new_run": True}
    run_days(env, control, 700)
    run_days(env, {"state": "running", "new_run": False}, 750)
    tmp = env[4]
    n1 = len(read_trades(tmp / "trades.csv")); e1 = len(open(tmp / "equity.csv").readlines())
    run_days(env, {"state": "running", "new_run": False}, 750)
    assert len(read_trades(tmp / "trades.csv")) == n1 and len(open(tmp / "equity.csv").readlines()) == e1


def test_pause_blocks_trades_but_marks_to_market(env):
    tmp = env[4]
    run_days(env, {"state": "running", "new_run": True}, 700)
    run_days(env, {"state": "running", "new_run": False}, 760)
    n = len(read_trades(tmp / "trades.csv"))
    run_days(env, {"state": "paused", "new_run": False}, 830)
    assert len(read_trades(tmp / "trades.csv")) == n                      # sem novas ordens
    rows = [r for r in csv.DictReader(open(tmp / "equity.csv")) if r["status"] == "paused"]
    assert len({r["date"] for r in rows}) == 70                           # mas marca a mercado todo dia


def test_stop_liquidates_and_closes_run(env):
    import json
    tmp = env[4]
    run_days(env, {"state": "running", "new_run": True}, 700)
    run_days(env, {"state": "running", "new_run": False}, 800)
    run_days(env, {"state": "stopped", "new_run": False}, 806)
    st = json.load(open(tmp / "paper.json"))
    assert st["active"] is False and st["closed_runs"][0]["reason"].startswith("interrompida")
    for p in st["portfolios"].values():
        assert p["sim"]["qty"] == {} and p["status"] == "closed"


def test_drawdown_halt_liquidates_active_but_not_passive(env, cfg):
    import dataclasses, json
    panel, c, strategies, weights, tmp = env
    c2 = Config(**{**c.__dict__, "risk": dataclasses.replace(c.risk, max_drawdown_halt=0.0001)})
    r = PaperRunner(c2, panel, strategies, weights, tmp)
    r.process({"state": "running", "new_run": True}, 700)
    r.process({"state": "running", "new_run": False}, 900)
    r.save()
    st = json.load(open(tmp / "paper.json"))["portfolios"]
    assert st["bh_btc"]["status"] == "active"                       # passiva não é interrompida
    halted = [k for k, p in st.items() if p["status"] in ("halted", "liquidating")]
    assert halted and all(st[k]["sim"]["qty"] == {} or st[k]["status"] == "liquidating" for k in halted)
    assert any(e["kind"] == "HALT" for e in r.events)


def test_missing_data_for_held_asset_skips_instead_of_losing_position(env):
    import json
    panel, cfg, strategies, weights, tmp = env
    run_days(env, {"state": "running", "new_run": True}, 700)
    run_days(env, {"state": "running", "new_run": False}, 760)
    st = json.load(open(tmp / "paper.json"))
    held = [a for p in st["portfolios"].values() for a in p["sim"]["qty"]]
    assert held
    sub = panel.subset([a for a in panel.ids if a != held[0]])           # ativo "sumiu" dos dados
    r = PaperRunner(cfg, sub, strategies, {k: v[:, [panel.col(a) for a in sub.ids]] for k, v in weights.items()}, tmp)
    r.process({"state": "running", "new_run": False}, 800)
    assert any(e["kind"] == "DATA_GAP" and e["severity"] == "critical" for e in r.events)
    after = json.load(open(tmp / "paper.json"))
    assert after["portfolios"] == st["portfolios"]                       # nada foi alterado/perdido
