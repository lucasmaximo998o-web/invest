"""Painel de mercado alinhado em calendário diário (todos os dias corridos).

Convenções (importantes para evitar vazamento de dados futuros):
  * `open/high/low/close` ficam NaN nos dias sem pregão do ativo (`tradable` = False);
  * `close_ff` é o último fechamento conhecido (usado só para marcação a mercado);
  * nenhum campo em t contém informação posterior a t.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import AssetSpec


@dataclass
class Panel:
    dates: pd.DatetimeIndex
    specs: list[AssetSpec]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    close_ff: np.ndarray
    volume: np.ndarray
    div: np.ndarray
    fx: np.ndarray  # multiplicador moeda nativa -> BRL (T, N)
    rf: np.ndarray  # CDI diário em decimal (T,)

    # ------------------------------------------------------------------ acesso
    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.specs]

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.specs)

    @property
    def tradable(self) -> np.ndarray:
        return ~np.isnan(self.open)

    def col(self, asset_id: str) -> int:
        return self.ids.index(asset_id)

    def close_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.close_ff, index=self.dates, columns=self.ids)

    def bars(self, asset_id: str) -> pd.DataFrame:
        """Barras nativas (apenas dias com pregão) de um ativo."""
        j = self.col(asset_id)
        df = pd.DataFrame(
            {"open": self.open[:, j], "high": self.high[:, j], "low": self.low[:, j],
             "close": self.close[:, j], "volume": self.volume[:, j]},
            index=self.dates,
        )
        return df.dropna(subset=["close"])

    def close_brl_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.close_ff * self.fx, index=self.dates, columns=self.ids)

    def index_of(self, d) -> int:
        """Posição da data `d` (a última data <= d)."""
        d = pd.Timestamp(d).normalize()
        pos = self.dates.searchsorted(d, side="right") - 1
        if pos < 0:
            raise KeyError(f"{d.date()} antes do início do painel")
        return int(pos)

    def truncate(self, end) -> "Panel":
        """Painel apenas com dados até `end` (inclusive) - usado nos testes de look-ahead."""
        k = self.index_of(end) + 1
        return self.head(k)

    def head(self, k: int) -> "Panel":
        return Panel(
            dates=self.dates[:k], specs=self.specs, open=self.open[:k], high=self.high[:k],
            low=self.low[:k], close=self.close[:k], close_ff=self.close_ff[:k],
            volume=self.volume[:k], div=self.div[:k], fx=self.fx[:k], rf=self.rf[:k],
        )

    def subset(self, asset_ids: list[str]) -> "Panel":
        idx = [self.col(a) for a in asset_ids]
        return Panel(
            dates=self.dates, specs=[self.specs[i] for i in idx], open=self.open[:, idx],
            high=self.high[:, idx], low=self.low[:, idx], close=self.close[:, idx],
            close_ff=self.close_ff[:, idx], volume=self.volume[:, idx], div=self.div[:, idx],
            fx=self.fx[:, idx], rf=self.rf,
        )


def _daily_rf(cdi: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """CDI por dia corrido. Dias sem divulgação dentro da série (fim de semana/feriado) = 0.
    Dias APÓS a última divulgação (defasagem de ~1 dia útil do BCB) usam a última taxa
    conhecida nos dias úteis (aproximação conservadora; a taxa muda raramente)."""
    s = cdi.reindex(dates)
    last = cdi.index.max()
    last_rate = float(cdi.iloc[-1])
    after = dates > last
    s[after & (dates.dayofweek < 5)] = last_rate
    return s.fillna(0.0).to_numpy(dtype=float)


def build_panel(frames: dict[str, pd.DataFrame], specs: list[AssetSpec], usdbrl: pd.Series,
                cdi: pd.Series, start, end) -> Panel:
    specs = [s for s in specs if s.id in frames and len(frames[s.id])]
    if not specs:
        raise ValueError("nenhum ativo com dados")
    start = max(pd.Timestamp(start), min(frames[s.id].index.min() for s in specs)).normalize()
    end = pd.Timestamp(end).normalize()
    dates = pd.date_range(start, end, freq="D")
    cols = {k: [] for k in ("open", "high", "low", "close", "volume", "div")}
    for s in specs:
        f = frames[s.id].reindex(dates)
        for k, c in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"),
                     ("volume", "volume"), ("div", "dividend")):
            cols[k].append(f[c].to_numpy(dtype=float))
    arr = {k: np.column_stack(v) for k, v in cols.items()}
    arr["volume"] = np.nan_to_num(arr["volume"], nan=0.0)
    arr["div"] = np.nan_to_num(arr["div"], nan=0.0)
    close_ff = pd.DataFrame(arr["close"], index=dates).ffill().to_numpy()
    usd = usdbrl.reindex(dates).ffill().bfill().to_numpy(dtype=float)
    fx = np.column_stack([usd if s.currency == "USD" else np.ones(len(dates)) for s in specs])
    return Panel(
        dates=dates, specs=specs, open=arr["open"], high=arr["high"], low=arr["low"],
        close=arr["close"], close_ff=close_ff, volume=arr["volume"], div=arr["div"], fx=fx,
        rf=_daily_rf(cdi, dates),
    )
