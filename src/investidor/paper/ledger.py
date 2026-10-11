"""Livro-razão da simulação (somente anexa) e persistência de estado em arquivos de texto.

O estado vive em arquivos simples versionados no git (branch `state`): cada ciclo vira um
commit, então todo o histórico é auditável e à prova de adulteração silenciosa. Cada linha de
operação carrega um hash encadeado (sha256 da linha + hash anterior) - `verify_ledger` detecta
qualquer edição ou remoção de linhas antigas.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path

TRADE_COLUMNS = ["seq", "date", "run_id", "portfolio", "asset", "side", "qty", "price_native", "fx",
                 "fill_price_brl", "notional_brl", "fee_brl", "slippage_brl", "reason", "mode", "prev_hash", "hash"]
EQUITY_COLUMNS = ["date", "run_id", "portfolio", "equity", "cash", "exposure", "drawdown", "status"]
GENESIS = "0" * 64


def write_json(path: Path, data) -> None:
    """Escrita atômica (evita arquivo corrompido se o processo cair no meio)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def read_jsonl(path: Path, last: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return rows[-last:] if last else rows


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _append_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def _row_hash(prev: str, row: dict) -> str:
    payload = prev + "|" + "|".join(str(row.get(c, "")) for c in TRADE_COLUMNS if c not in ("prev_hash", "hash"))
    return hashlib.sha256(payload.encode()).hexdigest()


def append_trades(path: Path, trades: list[dict]) -> int:
    """Anexa operações FICTÍCIAS ao livro-razão com hash encadeado. Devolve nº de linhas."""
    if not trades:
        return 0
    existing = _read_rows(path)
    prev = existing[-1]["hash"] if existing else GENESIS
    seq = int(existing[-1]["seq"]) + 1 if existing else 1
    out = []
    for t in trades:
        row = {**t, "seq": seq, "mode": "PAPER", "prev_hash": prev}
        row["hash"] = _row_hash(prev, row)
        prev = row["hash"]
        seq += 1
        out.append(row)
    _append_rows(path, TRADE_COLUMNS, out)
    return len(out)


def read_trades(path: Path) -> list[dict]:
    return _read_rows(path)


def verify_ledger(path: Path) -> tuple[bool, str]:
    prev = GENESIS
    for i, row in enumerate(_read_rows(path), start=1):
        if row["prev_hash"] != prev or row["hash"] != _row_hash(prev, row):
            return False, f"linha {i} (seq {row.get('seq')}) não confere com o encadeamento"
        prev = row["hash"]
    return True, "ok"


def append_equity(path: Path, rows: list[dict]) -> None:
    _append_rows(path, EQUITY_COLUMNS, rows)


def read_equity(path: Path) -> list[dict]:
    return _read_rows(path)
