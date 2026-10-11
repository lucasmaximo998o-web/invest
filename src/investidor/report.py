"""Relatório diário em Markdown (português) a partir do snapshot."""
from __future__ import annotations


def brl(x: float | None) -> str:
    if x is None:
        return "n/d"
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if x < 0 else ''}R$ {s}"


def pct(x: float | None, d: int = 1, sign: bool = False) -> str:
    if x is None:
        return "n/d"
    s = f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"
    return s.replace(".", ",")


STATE_LABEL = {"running": "▶️ em execução", "paused": "⏸️ pausada (mantém posições, sem novas ordens)",
               "stopped": "⏹️ interrompida"}


def render_markdown(snap: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"# INVESTIDOR AI — Relatório de {snap['as_of']}")
    a("")
    a("> ⚠️ **SIMULAÇÃO (paper trading).** Todo valor de carteira abaixo é **fictício**. Preços de mercado são "
      "dados reais; backtests são histórico simulado. **Nenhuma ordem real foi enviada** e nenhum dinheiro "
      "real foi movimentado. Rentabilidade passada não garante resultado futuro.")
    a("")
    ctl, run = snap["control"], snap["run"]
    a("## Situação")
    a(f"- Controle da simulação: **{STATE_LABEL.get(ctl['state'], ctl['state'])}** "
      f"(atualizado em {ctl.get('updated_at', 'n/d')} por {ctl.get('updated_by', 'n/d')})")
    a(f"- Rodada: `{run.get('run_id') or 'nenhuma'}` — início {run.get('start_date') or 'n/d'}, "
      f"capital fictício por carteira {brl(run.get('initial'))}")
    d = snap["data"]
    a(f"- Dados de mercado reais até **{snap['as_of']}** — {len(d['universe_used'])} ativos usados"
      + (f"; fora do ciclo: {', '.join(s['asset'] for s in d['skipped'])}" if d["skipped"] else ""))
    a(f"- Integridade do livro-razão: {'✅ ok' if snap['ledger']['integrity_ok'] else '❌ ' + snap['ledger']['detail']}")
    a("")
    prim = next((p for p in snap["portfolios"] if p["id"] == snap["primary"]), None)
    if prim:
        s = prim["summary"]
        a(f"## Carteira principal (SIMULADA): {prim['name']}")
        a("")
        a("| Capital inicial | Patrimônio | Lucro/Prejuízo | Rentabilidade | Drawdown atual | Drawdown máx. | Dias |")
        a("|---|---|---|---|---|---|---|")
        a(f"| {brl(s['initial'])} | {brl(s['equity'])} | {brl(s['pnl'])} | {pct(s['return'], 2, True)} | "
          f"{pct(s.get('current_drawdown'))} | {pct(s.get('max_drawdown'))} | {s['days']} |")
        a("")
        if prim["positions"]:
            a("**Posições (fictícias):**")
            a("")
            a("| Ativo | Quantidade | Preço | Valor |")
            a("|---|---|---|---|")
            for p in prim["positions"]:
                a(f"| {p['asset']} | {p['qty']:.6g} | {brl(p['price_brl'])} | {brl(p['value_brl'])} |")
            a(f"\nCaixa: {brl(prim['cash'])}")
        else:
            a("Sem posições abertas (100% em caixa).")
        if prim.get("halt_reason"):
            a(f"\n🛑 **Status:** {prim['status']} — {prim['halt_reason']}")
        a("")
    a("## Todas as carteiras simuladas")
    a("")
    a("| Carteira | Tipo | Patrimônio | Rentab. | Dreno atual | Status |".replace("Dreno", "Drawdown"))
    a("|---|---|---|---|---|---|")
    for p in sorted(snap["portfolios"], key=lambda p: -p["summary"]["return"]):
        s = p["summary"]
        tag = "passiva" if p["passive"] else p["family"]
        a(f"| {p['id']} | {tag} | {brl(s['equity'])} | {pct(s['return'], 2, True)} | "
          f"{pct(s.get('current_drawdown'))} | {p['status']} |")
    if snap["cdi_curve"]:
        c = snap["cdi_curve"]
        a(f"\nReferência CDI no mesmo período: {pct(c[-1][1] / c[0][1] - 1, 2, True)} (bruto de impostos).")
    a("")
    todays = [t for t in snap["trades"] if t["date"] == snap["as_of"]]
    a(f"## Operações fictícias em {snap['as_of']}: {len(todays)}")
    for t in todays[:20]:
        a(f"- {t['portfolio']}: {t['side']} {float(t['qty']):.6g} {t['asset']} a {brl(float(t['fill_price_brl']))} "
          f"(taxa {brl(float(t['fee_brl']))})")
    a("")
    a("## Alertas recentes")
    recent = snap["alerts"][:10]
    if recent:
        for al in recent:
            ico = {"critical": "🔴", "warning": "🟠"}.get(al["severity"], "ℹ️")
            a(f"- {ico} {al['date']} — {al['message']}")
    else:
        a("- Nenhum alerta.")
    a("")
    bt = snap.get("backtest")
    if bt:
        a("## Referência histórica (BACKTEST — não é resultado real)")
        a(f"Período {bt['period']['start']} a {bt['period']['end']}, capital de referência {brl(bt['initial_brl'])}, "
          "com custos; universo escolhido hoje (viés de sobrevivência/retrospecto).")
        a("")
        a("| Estratégia | CAGR | Vol. | Sharpe | Máx. DD | DSR |")
        a("|---|---|---|---|---|---|")
        for r in sorted(bt["leaderboard"], key=lambda r: -(r.get("sharpe") or -9))[:8]:
            a(f"| {r['id']} | {pct(r['cagr'])} | {pct(r['vol'])} | {r['sharpe']:.2f} | {pct(r['max_drawdown'])} | "
              f"{(r.get('dsr') or 0):.2f} |")
        a(f"\nCDI no período: {pct(bt['cdi']['cagr'])} a.a. DSR < 0,95 = sem evidência estatística após "
          "corrigir pelo número de estratégias testadas.")
        a("")
    a("## Qualidade dos dados")
    for n in d["notes"] or ["Sem avisos."]:
        a(f"- {n}")
    a("")
    a("---")
    a(f"*Gerado em {snap['generated_at']} · INVESTIDOR AI v{snap['version']} · modo PAPER.*")
    return "\n".join(L) + "\n"
