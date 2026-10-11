"""Fixtures: painel sintético (passeios aleatórios) para testar motor/estratégias sem rede."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investidor.config import AssetSpec, load_config
from investidor.data.panel import build_panel


def make_frames(T: int = 1500, seed: int = 0, start: str = "2020-01-01"):
    rng = np.random.default_rng(seed)
    specs = [
        AssetSpec("BTC", "Bitcoin", "crypto", "binance", "BTCUSDT", "USD", 1e-6),
        AssetSpec("ETH", "Ether", "crypto", "binance", "ETHUSDT", "USD", 1e-6),
        AssetSpec("SPY", "SPY", "us", "nasdaq", "SPY", "USD", 1e-4, assetclass="etf"),
        AssetSpec("GLD", "GLD", "us", "nasdaq", "GLD", "USD", 1e-4, assetclass="etf"),
        AssetSpec("PETR4", "Petro", "b3", "brapi", "PETR4", "BRL", 1.0),
    ]
    days = pd.date_range(start, periods=T, freq="D")
    frames = {}
    for i, s in enumerate(specs):
        idx = days if s.klass == "crypto" else days[days.dayofweek < 5]
        vol = {"crypto": 0.035, "us": 0.011, "b3": 0.018}[s.klass]
        r = rng.normal(0.0004, vol, len(idx))
        close = 50.0 * (1 + i) * np.exp(np.cumsum(r))
        prev = np.concatenate([[close[0]], close[:-1]])
        op = prev * (1 + rng.normal(0, vol / 4, len(idx)))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, vol / 4, len(idx))))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, vol / 4, len(idx))))
        div = np.zeros(len(idx))
        if s.id == "PETR4":
            div[200::120] = close[200::120] * 0.03
        frames[s.id] = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close,
                                     "volume": rng.uniform(1e5, 1e6, len(idx)), "dividend": div}, index=idx)
    usd = pd.Series(5.0 * np.exp(np.cumsum(rng.normal(0, 0.003, T))), index=days)
    cdi = pd.Series(0.0004, index=days[days.dayofweek < 5])
    return specs, frames, usd, cdi, days


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def panel():
    specs, frames, usd, cdi, days = make_frames()
    return build_panel(frames, specs, usd, cdi, days[0], days[-1])


@pytest.fixture()
def tiny_panel():
    """Painel pequeno (2 ativos) para casos de borda do motor."""
    specs, frames, usd, cdi, days = make_frames(T=200, seed=3)
    return build_panel({k: frames[k] for k in ("BTC", "PETR4")}, [s for s in specs if s.id in ("BTC", "PETR4")],
                       usd, cdi, days[0], days[-1])
