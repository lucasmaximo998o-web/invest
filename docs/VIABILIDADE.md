# Viabilidade técnica e financeira

> Resumo honesto: **tecnicamente é viável e já funciona** (dados reais, backtests, paper trading, painel, nuvem
> gratuita). **Financeiramente, com R$ 50, o resultado esperado em reais é pequeno** e **não há evidência de que
> alguma estratégia ativa supere o simples comprar-e-segurar** depois de custos e de corrigir o viés de escolha.

## 1. Viabilidade técnica

| Requisito | Solução | Status |
|---|---|---|
| Só um celular Android | Tudo roda na nuvem; o painel é um site; os controles são botões que abrem o GitHub | ✔ implementado |
| Celular desligado | GitHub Actions agenda e executa o ciclo diário | ✔ implementado (ver `docs/DEPLOY_CELULAR.md` para o que falta ativar) |
| Sem conversa aberta no Claude Code | O ciclo é um workflow agendado, independente do Claude | ✔ |
| Banco persistente | Arquivos de texto versionados no branch `state` (cada ciclo = 1 commit auditável) | ✔ |
| Monitoramento de erros | Erro do ciclo → registro em `runs.jsonl` + alerta crítico + Issue no GitHub (push no app) + e-mail do GitHub | ✔ |
| Credenciais seguras | Nenhuma credencial financeira existe. Chaves opcionais (brapi, ntfy) ficam em *GitHub Secrets* | ✔ |
| Custo | R$ 0: repositório público ⇒ Actions e Pages gratuitos, sem cartão | ✔ |
| Independente da "IA empreendedora" | Repositório, estado, workflows e segredos próprios; nenhum código compartilhado | ✔ |

### Fontes de dados (testadas em 2026-10-11)

| Mercado | API | Chave? | Observações |
|---|---|---|---|
| Cripto (BTC, ETH, SOL, BNB, XRP, ADA) | Binance Vision `data-api.binance.vision` | não | Histórico desde 2017/2018. `api.binance.com` retorna 451 em IPs dos EUA; o domínio *vision* funciona. |
| Ações/ETFs EUA | API pública da Nasdaq | não | Ajustada a *splits*; **sem dividendos** (retorno de preço ⇒ viés conservador de ~1–4 %/a.a. em ETFs/ações que pagam). |
| B3 | brapi.dev | só para tickers além de PETR4/VALE3/ITUB4/MGLU3 (token grátis) | Preço ajustado a splits; proventos derivados do `adjustedClose` e **conferidos** contra os dividendos reportados (R$ 41,3 vs R$ 42,4 em 5 anos de PETR4). |
| CDI e dólar | Banco Central (SGS 12 e 1) | não | Referência de renda fixa e conversão para reais. |
| Checagem cruzada | CoinGecko | não | Compara o preço atual da Binance com fonte independente (desvio observado < 0,2 %). |

**Não funcionou daqui:** Yahoo Finance (HTTP 429 do IP compartilhado) e Stooq (conexão recusada). Por isso não são usados.

### Limitações conhecidas dos dados
- Séries dos EUA sem dividendos; cripto em USDT (≈ USD) convertido pelo dólar do BCB.
- Preço de *abertura* diária de cripto coincide com o fechamento anterior (mercado 24/7): execução ligeiramente otimista (compensada por derrapagem de 5 bps).
- Universo escolhido **hoje** ⇒ viés de sobrevivência/retrospecto (NVDA ×70, BNB ×135 e SOL ×30 no período).
- Impostos **não** são modelados.

## 2. Viabilidade financeira com R$ 50

Calculado pelo próprio sistema (`aba Estudo → Viabilidade`) com preços reais do dia:

- **B3:** PETR4 (R$ 56) e VALE3 (R$ 68) **não cabem** numa posição de ~R$ 16,3 (1 ação > posição). Só ITUB4 (~R$ 50) chega perto. Mercado fracionário compra de 1 em 1 ação.
- **EUA:** só viável se a corretora vender **frações** de ações/ETFs. Custo de entrada premissado em ~1,1 % (IOF + câmbio) + 0,4 % na saída — **confirme na sua corretora**.
- **Cripto:** fracionável; taxas de corretora brasileira (0,1–0,5 %) pesam mais que em exchanges globais.
- **Ordem mínima:** configurada em R$ 10. Com 3 posições de R$ 16,3, uma queda de 40 % deixa as posições abaixo do mínimo e a estratégia **perde a capacidade de operar** (efeito visto no backtest com R$ 50).
- **Ordem de grandeza (não é previsão):** um ano excelente (+30 %) rende ~R$ 15; um ano ruim (−40 %) perde R$ 20. **Renda fixa a ~CDI rende ~R$ 5/ano** sem risco de capital.

**Conclusão financeira:** o valor de R$ 50 serve para *aprender e validar o processo*, não para gerar renda. A decisão racional hoje é manter o dinheiro intocado, deixar o paper trading acumular meses de resultados "para frente" e só então reavaliar.

## 3. Resultado dos backtests (histórico simulado, 2019-05 → 2026-10, custos incluídos)

Ver o placar completo na aba **Estudo** (atualiza semanalmente). Pontos-chave, medidos nos dados reais:

1. A referência **"comprar o universo inteiro em partes iguais"** teve Sharpe 1,05 e **bateu quase todas as estratégias ativas** — a maior parte do "ganho" das ativas vem de ter incluído, com retrospecto, ativos que explodiram.
2. **Walk-forward** (parâmetros escolhidos só no passado): `trend_sma` rendeu −3,7 % a.a. fora da amostra contra CDI de 12,1 %; ajustar parâmetros **não** melhorou de forma confiável.
3. **DSR** (Sharpe corrigido pelas ~45 tentativas): nenhuma estratégia ativa passa de 0,95. Estratégias de reversão (Bollinger/RSI) ficaram perto de zero ou abaixo do CDI.
4. O modelo de ML (gradient boosting) teve AUC fora da amostra ≈ 0,51 (acaso = 0,50): **sem evidência de poder preditivo**; mantido só como experimental.
5. Drawdowns de −60 % a −80 % em estratégias com cripto: incompatíveis com o limite de interrupção de 25 % do paper trading (ele *vai* interromper essas carteiras em algum momento — é o comportamento desejado).

> Nada disso é promessa de retorno. O que é verificável é o **processo**: dados auditáveis, custos, ausência de look-ahead (teste automatizado) e resultado "para frente" no paper trading.
