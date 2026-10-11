# Arquitetura

```
        ┌────────────────────── GitHub Actions (cron diário 01:31 UTC / manual / Issue do dono) ─────────────────────┐
        │                                                                                                           │
APIs →  │ data/providers → data/store (cache + qualidade) → data/panel (calendário diário, FX, CDI)                 │
reais   │        │                                                                                                  │
        │        ▼                                                                                                  │
        │ strategies/* (pesos-alvo causais) ──► sim/engine (execução com custos, lotes, sem alavancagem)            │
        │        │                                   │ mesmo código em dois usos                                    │
        │        │                       ┌───────────┴───────────┐                                                  │
        │        │                  sim/backtest             paper/runner (estado incremental, risco, controle)     │
        │        │              (walk-forward, DSR…)         ledger append-only (hash) + equity + alertas           │
        │        ▼                       │                       │                                                  │
        │   export.build_snapshot ◄──────┴───────────────────────┘                                                  │
        │        ├─► report.md (diário)        ├─► site/data/dashboard.json ─► GitHub Pages (painel)                │
        │        └─► branch `state` (commit)   └─► alertas críticos → Issues / ntfy                                 │
        └───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Decisões e motivos

**GitHub como infraestrutura única.** Requisitos: só celular, celular desligado, custo zero, sem cartão, credenciais seguras, monitoramento de erros. Actions (agendamento + cálculo), um branch de estado (persistência auditável), Pages (painel) e Issues/app do GitHub (alertas) cobrem tudo em uma conta que o usuário já tem. Alternativas descartadas: servidores "free tier" dormem e perdem disco (Render/HF), exigem cartão (Fly/GCP/AWS) ou são difíceis de operar por celular (VM própria).

**Um motor de execução para backtest e paper trading** (`sim/engine.py`). O paper trading é o backtest rodando um dia por vez; um teste automatizado garante que ambos dão o mesmo patrimônio (diferença < 1e-9) e que rodar 100 ciclos de 1 dia equivale a 1 ciclo de 100 dias (inclusive o hash do livro-razão).

**Sem look-ahead por construção e por teste.** Pesos em *t* só usam dados ≤ *t*; ordens executam na abertura de *t+1*. `tests/test_no_lookahead.py` trunca o painel, altera o futuro e compara — e inclui uma estratégia propositalmente "trapaceira" que o detector tem de reprovar. Modelos (ridge/GBM) re-treinam em datas fixas só com alvos já realizados.

**Estado em texto versionado.** `trades.csv` (hash encadeado), `equity.csv`, `paper.json`, `alerts.jsonl`, `runs.jsonl`, `backtest.json`, `control.json`. Cada ciclo é um commit no branch `state`: auditável, restaurável, e editar o passado quebra o hash (`investidor verify`). `concurrency` impede dois ciclos simultâneos.

**Controle sem servidor.** Botões do painel abrem uma Issue pré-preenchida (`/investidor pause`); o workflow só executa se o autor for o dono do repositório e só aceita uma lista fechada de ações (o título nunca é interpolado no shell).

**Honestidade estatística embutida.** Placar com DSR (corrige múltiplas tentativas), bootstrap, robustez "sem os maiores vencedores", referência "universo inteiro em partes iguais" para medir o viés de escolha, e walk-forward para qualquer ajuste de parâmetro.

**Degradação controlada.** API fora ⇒ cache (marcado) ou ativo excluído do ciclo, com alerta; dado velho nunca vira decisão; carteira com posição em ativo sem dado fica congelada (não perde posição) até o dado voltar; falha do ciclo é registrada, alertada e deixa o workflow vermelho.

## Mapa do código
`src/investidor/`: `config` (TOML + travas de modo) · `data/` (providers, store, quality, panel) · `indicators` · `strategies/` (base, library, models, registry) · `sim/` (engine, metrics, stats, backtest) · `paper/` (runner, ledger, control, analytics) · `alerts` · `feasibility` · `export` · `report` · `cycle` · `cli`. Painel: `site/`. Testes: `tests/`.
