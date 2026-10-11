"""Ciclo completo offline com cache sintético: dados -> sinais -> paper -> alertas -> relatório -> painel."""
import json

import pytest

from investidor.cycle import run_cycle
from investidor.paper.control import apply_action
from investidor.paper.ledger import verify_ledger
from .conftest import make_frames


@pytest.fixture()
def dirs(tmp_path):
    specs, frames, usd, cdi, days = make_frames(T=1500, seed=11)
    cache = tmp_path / "cache"; cache.mkdir()
    for k, df in frames.items():
        df.rename_axis("date").to_csv(cache / f"asset_{k}.csv")
    usd.rename("usdbrl").rename_axis("date").to_frame().to_csv(cache / "usdbrl.csv")
    cdi.rename("cdi").rename_axis("date").to_frame().to_csv(cache / "cdi.csv")
    return tmp_path, days


def test_full_cycle_offline(cfg, dirs):
    tmp, days = dirs
    state, out = tmp / "state", tmp / "out"
    res = run_cycle(cfg, state, tmp / "cache", out, as_of=days[1000].date(), offline=True, skip_backtest=True)
    assert res["run"]["status"] == "ok" and res["run"]["assets"] == 5
    snap = json.load(open(out / "data" / "dashboard.json"))
    assert snap["labels"]["dinheiro_real_movimentado_brl"] == 0 and snap["labels"]["modo"].startswith("PAPER")
    assert snap["golive"]["live_trading_enabled"] is False
    assert (out / "index.html").exists() and (out / "app.js").exists() and (out / "data" / "relatorio.md").exists()
    # dias seguintes
    run_cycle(cfg, state, tmp / "cache", out, as_of=days[1100].date(), offline=True, skip_backtest=True)
    snap = json.load(open(out / "data" / "dashboard.json"))
    assert snap["portfolios"] and all(p["summary"]["equity"] > 0 for p in snap["portfolios"])
    assert verify_ledger(state / "trades.csv")[0]
    # pausar, parar e reiniciar pelo mesmo caminho dos botões
    apply_action(state, "pause", "t"); run_cycle(cfg, state, tmp / "cache", out, as_of=days[1120].date(), offline=True, skip_backtest=True)
    apply_action(state, "stop", "t"); run_cycle(cfg, state, tmp / "cache", out, as_of=days[1140].date(), offline=True, skip_backtest=True)
    apply_action(state, "start", "t"); run_cycle(cfg, state, tmp / "cache", out, as_of=days[1160].date(), offline=True, skip_backtest=True)
    snap = json.load(open(out / "data" / "dashboard.json"))
    assert snap["control"]["state"] == "running" and snap["run"]["run_id"].endswith("-2") is False
    assert len(snap["run"]["closed_runs"]) == 1


def test_cycle_with_backtest_and_walk_forward(cfg, dirs):
    tmp, days = dirs
    res = run_cycle(cfg, tmp / "state", tmp / "cache", tmp / "out", as_of=days[-1].date(), offline=True)
    bt = json.load(open(tmp / "state" / "backtest.json"))
    ids = {r["id"] for r in bt["leaderboard"]}
    assert {"bh_btc", "ew_all", "dual_momentum", "ml_gbm"} <= ids
    assert bt["kind"] == "BACKTEST_HISTORICO" and bt["walk_forward"]
    for r in bt["leaderboard"]:
        assert r["max_drawdown"] <= 0 and r["r50"] is not None
    assert "survivorship" in bt["assumptions"]


def test_cycle_failure_is_recorded_and_alerted(cfg, tmp_path):
    with pytest.raises(Exception):
        run_cycle(cfg, tmp_path / "state", tmp_path / "empty_cache", tmp_path / "out", offline=True, skip_backtest=True)
    runs = [json.loads(l) for l in open(tmp_path / "state" / "runs.jsonl")]
    assert runs[-1]["status"] == "error"
    alerts = [json.loads(l) for l in open(tmp_path / "state" / "alerts.jsonl")]
    assert alerts[-1]["kind"] == "CICLO_ERRO" and alerts[-1]["severity"] == "critical"
    assert json.load(open(tmp_path / "out" / "new_alerts.json"))[0]["severity"] == "critical"
