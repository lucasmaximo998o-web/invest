# INVESTIDOR AI

Pesquisa quantitativa, backtests honestos e **paper trading** (dinheiro fictício) automatizados na nuvem, com
painel para celular. **Não opera dinheiro real e não promete retorno.**

> ⚠️ **Leia antes:** resultados históricos não garantem nada. Com R$ 50 o ganho esperado em reais é pequeno
> (um ano excelente rende ~R$ 15; renda fixa a CDI rende ~R$ 5) e os testes **não encontraram evidência** de que
> as estratégias ativas superem comprar-e-segurar após custos. Veja [`docs/VIABILIDADE.md`](docs/VIABILIDADE.md).

## O que faz

- **Dados reais** (APIs públicas): cripto (Binance Vision), ações/ETFs EUA (Nasdaq), B3 (brapi), CDI e dólar (BCB), com cache, controle de qualidade e checagem cruzada de preços.
- **12 estratégias** comparáveis: passivas (BTC, S&P 500, cesta BTC/SPY/GLD, universo inteiro), momentum dual, médias móveis 50/200, MACD, Bollinger, RSI, baixa volatilidade, regressão ridge e gradient boosting (ML só com dados suficientes).
- **Backtest sem vazamento do futuro**: sinal no fechamento de *t*, ordem na abertura de *t+1*, com taxas, spread, derrapagem, IOF/câmbio (premissas), lote e ordem mínimos. Teste automatizado de look-ahead (com teste de mutação).
- **Validação fora da amostra**: walk-forward (escolhe parâmetros no passado, mede no futuro), Sharpe deflacionado (DSR) pelas tentativas, bootstrap em blocos, teste "sem os maiores vencedores" e comparação com referências passivas e CDI.
- **Paper trading** diário: 12 carteiras fictícias de R$ 50, livro-razão com hash encadeado, limite de perda (−25 % ⇒ liquida e interrompe), alertas, relatório diário.
- **Painel mobile** (GitHub Pages) com rótulos que separam **● dados reais**, **◆ simulação** e **▲ histórico**; botões iniciar/pausar/interromper.
- **Nuvem gratuita**: GitHub Actions agenda o ciclo (celular desligado), estado versionado no branch `state`, alertas críticos viram Issues (push no app do GitHub) e/ou ntfy.

## Colocar no ar (só com o celular)
[`docs/DEPLOY_CELULAR.md`](docs/DEPLOY_CELULAR.md) — 3 passos principais: *merge* do PR, ativar Pages, rodar o primeiro ciclo.

## Documentação
| Arquivo | Conteúdo |
|---|---|
| [`docs/VIABILIDADE.md`](docs/VIABILIDADE.md) | Viabilidade técnica e financeira, fontes de dados, limitações, resultados dos backtests |
| [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | Como as peças se encaixam e por que cada escolha foi feita |
| [`docs/DEPLOY_CELULAR.md`](docs/DEPLOY_CELULAR.md) | Autorizações e passos pelo celular; uso do painel |
| [`docs/INTEGRACAO_REAL.md`](docs/INTEGRACAO_REAL.md) | Por que não há ordens reais e o que seria exigido antes |

## Uso local (opcional)
```bash
pip install -e ".[dev]"
python -m pytest                      # 65 testes, sem rede
investidor backtest                   # baixa dados reais e imprime o placar (~2 min)
investidor cycle --skip-backtest      # um ciclo completo: gera ./state e ./_site
investidor serve                      # painel em http://127.0.0.1:8000
investidor control pause              # pausar / resume / stop / start
investidor verify                     # confere o hash encadeado do livro-razão
```
Configuração: [`config/investidor.toml`](config/investidor.toml) (universo, custos, limites de risco). Os parâmetros das estratégias foram fixados *antes* de olhar resultados; não os ajuste olhando o backtest completo.

## Limitações assumidas
Universo escolhido hoje (viés de sobrevivência/retrospecto) · EUA sem dividendos · custos e IOF são premissas · impostos não modelados · cripto: abertura diária = fechamento anterior · ML sem evidência de ganho. Detalhes em `docs/VIABILIDADE.md`.
