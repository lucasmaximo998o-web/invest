"""Provedores de dados de mercado (APIs públicas, sem chave obrigatória).

Todos devolvem DataFrame indexado por data (naive, normalizada) com colunas
  open, high, low, close, volume, dividend
em moeda nativa do ativo. `dividend` = provento em dinheiro por unidade na data
ex (0 quando não houver / não for conhecido).

Fontes (verificadas em 2026-10-11):
  * Binance Vision  data-api.binance.vision   cripto spot (USDT), diário
  * Nasdaq          api.nasdaq.com            ações/ETFs EUA (ajustado a splits,
                                              SEM dividendos)
  * brapi           brapi.dev                 B3 (preço ajustado a splits; proventos
                                              derivados do adjustedClose)
  * BCB SGS         api.bcb.gov.br            CDI (série 12) e dólar (série 1)
  * CoinGecko       api.coingecko.com         apenas checagem cruzada de preço
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "application/json",
}
COLUMNS = ["open", "high", "low", "close", "volume", "dividend"]


class DataError(RuntimeError):
    pass


def http_get(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: float = 30, retries: int = 4, backoff: float = 2.0) -> requests.Response:
    """GET com retentativas e backoff exponencial para erros transitórios."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = DataError(f"HTTP {r.status_code} em {url}")
            elif r.status_code >= 400:
                raise DataError(f"HTTP {r.status_code} em {url}: {r.text[:200]}")
            else:
                return r
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
        time.sleep(backoff * (2 ** attempt))
    raise DataError(f"falha após {retries} tentativas: {url}: {last}")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], name="date"), dtype=float)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).normalize()
    df.index.name = "date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in COLUMNS:
        if c not in df:
            df[c] = 0.0
    df = df[COLUMNS].astype(float)
    df["dividend"] = df["dividend"].fillna(0.0)
    return df.dropna(subset=["open", "high", "low", "close"])


# --------------------------------------------------------------------------- Binance
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"


def fetch_binance(symbol: str, start: str | date, now: datetime | None = None) -> pd.DataFrame:
    """Candles diários (UTC). Descarta o candle ainda em formação."""
    now = now or datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    start_ms = int(pd.Timestamp(start).tz_localize("UTC").timestamp() * 1000)
    rows: list[list] = []
    while True:
        r = http_get(BINANCE_URL, {"symbol": symbol, "interval": "1d", "limit": 1000, "startTime": start_ms})
        chunk = r.json()
        if not isinstance(chunk, list):
            raise DataError(f"resposta inesperada da Binance para {symbol}: {str(chunk)[:200]}")
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start_ms = chunk[-1][0] + 86_400_000
    if not rows:
        return _empty()
    df = pd.DataFrame(rows).iloc[:, :7]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    df = df[df["close_time"].astype("int64") < now_ms]  # candle fechado
    df.index = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True).dt.tz_localize(None)
    return _finish(df[["open", "high", "low", "close", "volume"]].astype(float))


# --------------------------------------------------------------------------- Nasdaq
NASDAQ_URL = "https://api.nasdaq.com/api/quote/{symbol}/historical"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).replace({"N/A": None}),
        errors="coerce",
    )


def fetch_nasdaq(symbol: str, assetclass: str, start: str | date, end: str | date | None = None) -> pd.DataFrame:
    end = end or date.today()
    r = http_get(
        NASDAQ_URL.format(symbol=symbol),
        {"assetclass": assetclass, "fromdate": str(pd.Timestamp(start).date()),
         "todate": str(pd.Timestamp(end).date()), "limit": 9999},
    )
    body = r.json()
    rows = ((body.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        raise DataError(f"Nasdaq sem dados para {symbol}: {str(body.get('status'))[:200]}")
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["date"], format="%m/%d/%Y")
    out = pd.DataFrame({c: _num(df[c]) for c in ["open", "high", "low", "close", "volume"]})
    out.index = df.index
    out["volume"] = out["volume"].fillna(0.0)
    return _finish(out)


# --------------------------------------------------------------------------- brapi
BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_DIVIDEND_MIN = 0.002  # 0,2% do preço: abaixo disso é ruído de arredondamento


def parse_brapi(payload: dict) -> pd.DataFrame:
    """Converte a resposta do brapi. Preço = fechamento ajustado a splits;
    proventos em dinheiro derivados de adjustedClose: D_t = (adj_t/adj_{t-1})*close_{t-1} - close_t.
    (Conferido contra `dividendsData.cashDividends` do próprio brapi: PETR4 5 anos,
    R$ 41,3 derivado vs R$ 42,4 reportado.)"""
    if payload.get("error"):
        raise DataError(f"brapi: {payload.get('message')}")
    res = (payload.get("results") or [None])[0]
    hist = (res or {}).get("historicalDataPrice") or []
    if not hist:
        raise DataError("brapi sem histórico")
    df = pd.DataFrame(hist)
    idx = pd.to_datetime(df["date"], unit="s", utc=True).dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    df.index = idx.dt.normalize()
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    adj = df["adjustedClose"].astype(float) if "adjustedClose" in df else df["close"].astype(float)
    close = df["close"].astype(float)
    implied = (adj / adj.shift(1)) * close.shift(1) - close
    div = implied.where(implied > BRAPI_DIVIDEND_MIN * close.shift(1), 0.0).fillna(0.0)
    out = df[["open", "high", "low", "close", "volume"]].astype(float)
    out["dividend"] = div
    return _finish(out)


def fetch_brapi(symbol: str, token: str | None, rng: str = "10y") -> pd.DataFrame:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    r = http_get(BRAPI_URL.format(symbol=symbol), {"range": rng, "interval": "1d"}, headers=headers)
    return parse_brapi(r.json())


# --------------------------------------------------------------------------- BCB SGS
BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"


def fetch_bcb(code: int, start: str | date, end: str | date | None = None) -> pd.Series:
    """Série do SGS/BCB. Consulta em janelas de <= 9 anos (limite da API p/ séries diárias)."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end or date.today())
    parts: list[pd.Series] = []
    cur = s
    while cur <= e:
        win_end = min(cur + pd.DateOffset(years=9) - pd.Timedelta(days=1), e)
        r = http_get(BCB_URL.format(code=code), {
            "formato": "json",
            "dataInicial": cur.strftime("%d/%m/%Y"),
            "dataFinal": win_end.strftime("%d/%m/%Y"),
        })
        data = r.json()
        if isinstance(data, dict):  # erro estruturado
            raise DataError(f"BCB série {code}: {data}")
        if data:
            d = pd.DataFrame(data)
            parts.append(pd.Series(pd.to_numeric(d["valor"]).values,
                                   index=pd.to_datetime(d["data"], format="%d/%m/%Y")))
        cur = win_end + pd.Timedelta(days=1)
    if not parts:
        raise DataError(f"BCB série {code} vazia")
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index = out.index.normalize()
    return out.astype(float)


def fetch_cdi_daily(start: str | date, end: str | date | None = None) -> pd.Series:
    """CDI diário (decimal, ex.: 0.00050788 = 0,050788% ao dia). SGS 12 vem em % a.d."""
    return fetch_bcb(12, start, end) / 100.0


def fetch_usdbrl(start: str | date, end: str | date | None = None) -> pd.Series:
    """Dólar comercial (venda) SGS 1, R$ por US$."""
    return fetch_bcb(1, start, end)


# --------------------------------------------------------------------------- CoinGecko (cross-check)
def fetch_coingecko_spot(ids: list[str]) -> dict[str, float]:
    r = http_get("https://api.coingecko.com/api/v3/simple/price",
                 {"ids": ",".join(ids), "vs_currencies": "usd"}, retries=2)
    return {k: float(v["usd"]) for k, v in r.json().items() if "usd" in v}


def fetch_binance_spot(symbols: list[str]) -> dict[str, float]:
    import json
    r = http_get("https://data-api.binance.vision/api/v3/ticker/price",
                 {"symbols": json.dumps(symbols, separators=(",", ":"))}, retries=2)
    return {x["symbol"]: float(x["price"]) for x in r.json()}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def default_as_of() -> date:
    """Última data com barra diária COMPLETA em qualquer mercado: ontem (UTC)."""
    return utc_today() - timedelta(days=1)


__all__ = [
    "COLUMNS", "DataError", "fetch_binance", "fetch_nasdaq", "fetch_brapi", "parse_brapi",
    "fetch_bcb", "fetch_cdi_daily", "fetch_usdbrl", "fetch_coingecko_spot",
    "fetch_binance_spot", "default_as_of",
]
