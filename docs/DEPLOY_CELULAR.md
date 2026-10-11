# Implantação e uso 100% pelo celular (Android)

Tudo abaixo é feito no navegador do celular (Chrome) ou no app **GitHub** (opcional, recomendado para receber avisos).
Custo: **R$ 0**, sem cartão. Tempo: ~10 minutos.

## Como o sistema roda sem o seu celular

```
GitHub Actions (agendador gratuito, roda todo dia ~22:31 de Brasília)
   └─ baixa preços reais → calcula sinais → simula ordens (dinheiro FICTÍCIO)
      → grava o estado no branch `state` (cada ciclo = 1 commit auditável)
      → publica o painel no GitHub Pages
Você: abre o painel no navegador (ou o app do GitHub avisa de alertas).
```

Nada depende do celular ligado nem de uma conversa aberta no Claude Code.

## Passo 1 — Colocar o código no branch principal (obrigatório, 2 toques)

O GitHub só executa agendamentos de workflows que estão no branch `main`.

1. Abra `github.com/lucasmaximo998o-web/invest` → aba **Pull requests**.
2. Abra o PR do branch `claude/investidor-ai-financial-automation-nsc32l` (se não existir, toque em *Compare & pull request*).
3. Toque em **Merge pull request** → **Confirm merge**.

## Passo 2 — Ativar o painel (GitHub Pages) (1 minuto)

1. No repositório: **Settings** → **Pages**.
2. Em **Build and deployment → Source**, escolha **GitHub Actions**.

O endereço do painel será **https://lucasmaximo998o-web.github.io/invest/** (guarde nos favoritos / adicione à tela inicial: Chrome → ⋮ → *Adicionar à tela inicial*).

## Passo 3 — Rodar o primeiro ciclo agora

1. Aba **Actions** → workflow **Ciclo diário (paper trading)** → **Run workflow**.
2. Deixe `action = nenhuma` e toque **Run workflow**. Leva ~3–6 minutos na primeira vez (calcula o backtest completo).
3. Quando ficar verde ✔, abra o painel. A simulação começa com **R$ 50 fictícios por carteira**; as primeiras ordens são executadas na abertura do dia seguinte.

> A partir daí o ciclo roda sozinho todo dia, com o celular desligado.

## Passo 4 — Receber alertas no celular (escolha um ou ambos)

**A) App do GitHub (sem criar conta nova):** instale o app *GitHub*, entre na sua conta, abra o repositório → **Watch** → *Custom* → marque **Issues** e **Actions**. Alertas críticos (limite de perda atingido, falha de dados, falha do ciclo) viram **Issues** com rótulo `alerta` e chegam como notificação push. Falhas do workflow também chegam por e-mail do GitHub.

**B) ntfy (push direto, grátis, sem conta):**
1. Instale o app **ntfy** (Play Store) e assine um tópico com nome longo e aleatório, ex.: `investidor-ai-x7k2q9m4vz8`.
2. No repositório: **Settings → Secrets and variables → Actions → New repository secret** → nome `NTFY_TOPIC`, valor = o nome do tópico.
(Quem souber o nome do tópico lê as mensagens; por isso o nome deve ser secreto.)

## Passo 5 — (Opcional) Liberar mais ações da B3

Sem token, o brapi gratuito só libera PETR4, VALE3 e ITUB4. Para BOVA11/IVVB11 e outros: crie conta gratuita em **brapi.dev**, copie o token e salve em **Settings → Secrets → Actions** como `BRAPI_TOKEN`. (Com R$ 50 a maioria das ações da B3 nem cabe na posição — ver aba *Estudo → Viabilidade*.)

## Usando o painel

| Aba | O que mostra | Rótulo |
|---|---|---|
| **Resumo** | Capital inicial simulado, patrimônio, lucro/prejuízo, rentabilidade, drawdown, gráfico vs. referências passivas, alertas | ◆ SIMULAÇÃO |
| **Carteiras** | As 12 carteiras fictícias (cada uma com R$ 50), posições e custos | ◆ SIMULAÇÃO |
| **Operações** | Livro-razão de ordens fictícias (hash encadeado) | ◆ SIMULAÇÃO |
| **Risco** | Drawdown, VaR/CVaR, limites ativos, qualidade dos dados | ◆ / ● |
| **Alertas** | Perdas, mudanças de mercado, falhas | — |
| **Estudo** | Backtests, walk-forward, robustez, viabilidade com R$ 50, porta para dinheiro real | ▲ HISTÓRICO |
| **Controle** | Iniciar / Pausar / Retomar / Interromper | — |

Rótulos: **● DADOS REAIS** = preços/câmbio de mercado · **◆ SIMULAÇÃO** = paper trading, dinheiro fictício · **▲ HISTÓRICO** = backtest. A seção *Dinheiro real* do Resumo mostra sempre **R$ 0,00 movimentados**.

### Botões (Controle)
Tocar em **Pausar / Retomar / Interromper / Iniciar** abre o GitHub com uma Issue já preenchida (`/investidor pause` etc.). Basta tocar em **Submit new issue**. Em ~1 minuto o workflow aplica o comando, fecha a Issue e republica o painel.
Só funciona para o **dono do repositório** (qualquer outra pessoa é ignorada). Alternativa: Actions → *Run workflow* → escolher a ação.

- **Pausar:** mantém posições, para de operar, continua marcando a mercado.
- **Interromper:** vende tudo na próxima abertura e encerra a rodada. **Iniciar** depois abre uma rodada nova.
- **Limite de perda:** uma carteira ativa que cair 25 % desde o pico é liquidada e interrompida automaticamente (alerta crítico).

## Dinheiro real
Nada é enviado a corretoras. Os R$ 50 reservados não são tocados. Ver `docs/INTEGRACAO_REAL.md`.

## Problemas comuns
- *Painel diz "Ainda não há dados"*: faltou o Passo 2 ou o Passo 3.
- *Banner vermelho "Dados atrasados"*: o ciclo não rodou há > 36 h; veja Actions (o GitHub desativa agendamentos de repositórios sem atividade por 60 dias — basta rodar manualmente uma vez ou fazer qualquer commit).
- *Ativo aparece em "Fora do ciclo"*: API do ativo falhou ou exige token; a carteira que tem posição nele fica congelada com alerta crítico até o dado voltar.
