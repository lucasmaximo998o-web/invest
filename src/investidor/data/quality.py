"""Checagens de qualidade dos dados. Dados ruins viram alertas e, se graves, exclusão do ativo."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..config import AssetSpec

BLOCKING = "bloqueante"
WARNING = "aviso"


def assess(df: pd.DataFrame, spec: AssetSpec, as_of: date, stale_days: int) -> dict:
    """Retorna métricas e lista de problemas (severidade 'bloqueante' exclui o ativo do ciclo)."""
    issues: list[dict] = []

    def add(sev: str, msg: str) -> None:
        issues.append({"severity": sev, "message": msg})

    if df is None or df.empty:
        add(BLOCKING, "sem dados")
        return {"asset": spec.id, "rows": 0, "issues": issues, "ok": False}

    n = len(df)
    first, last = df.index.min(), df.index.max()
    lag = (pd.Timestamp(as_of) - last).days
    if lag > stale_days:
        add(BLOCKING, f"dados atrasados: última barra {last.date()} ({lag} dias antes de {as_of})")
    prices = df[["open", "high", "low", "close"]]
    nonpos = int((prices <= 0).any(axis=1).sum())
    if nonpos:
        add(BLOCKING, f"{nonpos} barras com preço <= 0")
    bad = int(((df["high"] < df["low"]) | (df["close"] > df["high"] * 1.0005)
               | (df["close"] < df["low"] * 0.9995)).sum())
    if bad:
        add(WARNING, f"{bad} barras com OHLC inconsistente")
    rets = df["close"].pct_change().abs()
    ext = int((rets > 0.5).sum())
    if ext:
        add(WARNING, f"{ext} variações diárias > 50% (conferir splits/erros)")
    if spec.klass == "crypto":
        missing = len(pd.date_range(first, last)) - n
        if missing > 0:
            add(WARNING, f"{missing} dias faltando em série 24/7")
    else:
        max_gap = int(df.index.to_series().diff().dt.days.max() or 0)
        if max_gap > 10:
            add(WARNING, f"buraco de {max_gap} dias entre barras")
    zero_vol = float((df["volume"] <= 0).mean())
    if zero_vol > 0.05 and spec.klass != "b3":
        add(WARNING, f"{zero_vol:.0%} das barras sem volume")
    tail = df.tail(60)
    adv_native = float((tail["close"] * tail["volume"]).median())
    blocking = any(i["severity"] == BLOCKING for i in issues)
    return {
        "asset": spec.id, "rows": n, "first": str(first.date()), "last": str(last.date()),
        "lag_days": lag, "adv_native_60d": adv_native, "issues": issues, "ok": not blocking,
    }
