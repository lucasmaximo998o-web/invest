import json

import numpy as np
import pandas as pd
import pytest

from investidor.data import providers as P
from investidor.data.quality import assess
from investidor.config import AssetSpec


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, json.dumps(payload)[:100]

    def json(self):
        return self._p


def test_binance_drops_unfinished_candle(monkeypatch):
    day = 86_400_000
    base = 1_700_000_000_000 // day * day
    rows = [[base + i * day, "10", "11", "9", "10.5", "100", base + (i + 1) * day - 1] for i in range(3)]
    monkeypatch.setattr(P, "http_get", lambda *a, **k: FakeResp(rows))
    # "agora" = meio do 3º candle -> ele ainda não fechou e tem que ser descartado
    now = pd.Timestamp(base + 2 * day + 3_600_000, unit="ms", tz="UTC").to_pydatetime()
    df = P.fetch_binance("BTCUSDT", "2023-11-01", now=now)
    assert len(df) == 2 and df.index.is_monotonic_increasing


def test_binance_rejects_error_payload(monkeypatch):
    monkeypatch.setattr(P, "http_get", lambda *a, **k: FakeResp({"code": -1121, "msg": "Invalid symbol."}))
    with pytest.raises(P.DataError):
        P.fetch_binance("XXXX", "2023-01-01")


def test_nasdaq_parses_currency_and_commas(monkeypatch):
    body = {"data": {"tradesTable": {"rows": [
        {"date": "10/09/2026", "close": "$336.64", "volume": "37,881,200", "open": "$331.695", "high": "$338.61", "low": "$330.70"},
        {"date": "10/08/2026", "close": "$330.00", "volume": "N/A", "open": "$329.0", "high": "$331.0", "low": "$328.5"}]}}}
    monkeypatch.setattr(P, "http_get", lambda *a, **k: FakeResp(body))
    df = P.fetch_nasdaq("AAPL", "stocks", "2026-10-01")
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-10-08", "2026-10-09"]
    assert df["close"].iloc[-1] == 336.64 and df["volume"].iloc[0] == 0.0


def test_nasdaq_empty_is_error(monkeypatch):
    monkeypatch.setattr(P, "http_get", lambda *a, **k: FakeResp({"data": None, "status": {"rCode": 400}}))
    with pytest.raises(P.DataError):
        P.fetch_nasdaq("ZZZZ", "etf", "2026-01-01")


def test_brapi_dividend_derivation():
    # 3 dias: dia 2 é data ex de R$ 1,00 sobre preço ~R$ 20 (5%)
    close = [20.0, 19.0, 19.2]
    adj = [19.0 * 0 + 18.1, 18.1 / 19.0 * 19.0 + 0, 19.2]  # placeholders sobrescritos abaixo
    # série ajustada coerente: retorno ajustado do dia 2 = (19+1)/20 - 1 = 0%
    adj = [20.0 * 0.95, 19.0 * 0.95 + 1.0 * 0.95 * 0, 0]
    adj0 = 20.0; adj1 = adj0 * (19.0 + 1.0) / 20.0; adj2 = adj1 * 19.2 / 19.0
    payload = {"results": [{"historicalDataPrice": [
        {"date": 1_790_000_000 + i * 86_400, "open": c, "high": c, "low": c, "close": c, "volume": 1, "adjustedClose": a}
        for i, (c, a) in enumerate(zip(close, [adj0, adj1, adj2]))]}]}
    df = P.parse_brapi(payload)
    assert df["dividend"].iloc[1] == pytest.approx(1.0, rel=1e-6)
    assert df["dividend"].iloc[0] == 0 and df["dividend"].iloc[2] == pytest.approx(0, abs=1e-9)


def test_brapi_token_error_is_surfaced():
    with pytest.raises(P.DataError, match="Token"):
        P.parse_brapi({"error": True, "message": "Token de autenticação não fornecido"})


def test_bcb_windowing_and_scaling(monkeypatch):
    calls = []

    def fake(url, params=None, **k):
        calls.append(params)
        return FakeResp([{"data": params["dataInicial"], "valor": "0.050788"}])

    monkeypatch.setattr(P, "http_get", fake)
    s = P.fetch_cdi_daily("2005-01-01", "2026-10-01")
    assert len(calls) >= 3  # janelas de <= 9 anos
    assert s.iloc[0] == pytest.approx(0.00050788)


def test_http_get_retries_then_raises(monkeypatch):
    seen = {"n": 0}

    class R:
        status_code = 503; text = "x"

    def fake_get(*a, **k):
        seen["n"] += 1
        return R()

    monkeypatch.setattr(P.requests, "get", fake_get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    with pytest.raises(P.DataError):
        P.http_get("http://x", retries=3)
    assert seen["n"] == 3


def test_quality_flags_stale_and_bad_prices():
    spec = AssetSpec("X", "X", "us", "nasdaq", "X", "USD", 0.01)
    idx = pd.date_range("2026-01-01", periods=30, freq="B")
    df = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1e6, "dividend": 0.0}, index=idx)
    ok = assess(df, spec, idx[-1].date(), 5)
    assert ok["ok"]
    stale = assess(df, spec, (idx[-1] + pd.Timedelta(days=20)).date(), 5)
    assert not stale["ok"] and "atrasados" in stale["issues"][0]["message"]
    bad = df.copy(); bad.iloc[3, 3] = -1.0
    assert not assess(bad, spec, idx[-1].date(), 5)["ok"]
