import json
import os

import pytest
import requests

from investidor import alerts as A
from investidor import cli
from investidor.config import ConfigError, assert_paper_mode, load_config
from investidor.feasibility import golive_gate


def test_default_config_is_paper_only(cfg):
    assert cfg.mode == "paper"
    assert_paper_mode(cfg)


def test_real_mode_in_config_is_rejected(tmp_path, cfg):
    p = tmp_path / "c.toml"
    p.write_text(cfg.path.read_text().replace('mode = "paper"', 'mode = "live"'))
    with pytest.raises(ConfigError):
        load_config(p)


@pytest.mark.parametrize("var,val", [("INVESTIDOR_LIVE", "1"), ("INVESTIDOR_MODE", "live")])
def test_env_cannot_enable_live(monkeypatch, cfg, var, val):
    monkeypatch.setenv(var, val)
    with pytest.raises(ConfigError):
        assert_paper_mode(cfg)


def test_no_broker_or_order_api_in_source():
    """Defesa em profundidade: o código não contém clientes de corretora/exchange para ordens."""
    import pathlib, re
    src = "\n".join(p.read_text() for p in pathlib.Path("src").rglob("*.py"))
    for pat in (r"api\.binance\.com/api/v3/order", r"/api/v3/order", r"create_order", r"place_order",
                r"requests\.(post|put|delete)\([^)]*(order|trade)", r"api_key|secret_key|API_SECRET"):
        assert not re.search(pat, src, re.I), f"padrão proibido encontrado: {pat}"


def test_issue_command_whitelist(tmp_path, monkeypatch):
    base = ["--state-dir", str(tmp_path)]
    assert cli.main(base + ["control-from-title", "--title", "/investidor pause", "--actor", "dono"]) == 0
    assert json.load(open(tmp_path / "control.json"))["state"] == "paused"
    for bad in ["/investidor pause; rm -rf /", "/investidor $(whoami)", "/investidor sell", "pause",
                "/investidor ", "/investidor stop && curl evil", "/investidor\npause"]:
        rc = cli.main(base + ["control-from-title", "--title", bad])
        assert rc != 0, bad
    assert json.load(open(tmp_path / "control.json"))["state"] == "paused"   # nada mudou


def test_alert_dedup_and_ntfy_optional(monkeypatch):
    sent = []
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append((a, k)) or type("R", (), {"ok": True})())
    al = [A.make("DRAWDOWN", "warning", "x", "2026-01-01", "p")]
    assert A.notify(al) == 0 and not sent                        # sem tópico: nada é enviado
    monkeypatch.setenv("NTFY_TOPIC", "segredo-teste")
    assert A.notify(al + [A.make("X", "info", "y", "2026-01-01")]) == 1   # info não notifica
    assert sent[0][0][0].endswith("/segredo-teste") and "Title" in sent[0][1]["headers"]
    assert all(ord(c) < 128 for c in sent[0][1]["headers"]["Title"])      # cabeçalho ASCII (evita erro HTTP)


def test_notify_never_raises(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    def boom(*a, **k): raise requests.ConnectionError("fora do ar")
    monkeypatch.setattr(requests, "post", boom)
    assert A.notify([A.make("X", "critical", "m", "2026-01-01")]) == 0


def test_golive_gate_never_enables_live(cfg):
    g = golive_gate(cfg, {"summary": {"max_drawdown": -0.05}}, {"leaderboard": [{"id": cfg.primary_strategy, "dsr": 0.99}]},
                    paper_days=400, critical_alerts_30d=0,
                    feas=[{"feasible": True}, {"feasible": True}, {"feasible": False}])
    assert g["automated_ok"] and g["live_trading_enabled"] is False
    assert any(c["manual"] and c["ok"] is None for c in g["criteria"])      # autorização/idade sempre manuais
