# Integração com dinheiro real — NÃO existe e NÃO é habilitada automaticamente

**Estado atual: 100 % paper trading.** O código não contém cliente de corretora/exchange, chaves de API nem rota de
envio de ordens. Isso é verificado por teste automatizado (`tests/test_safety.py`): o build falha se aparecer
`create_order`, `place_order`, `/api/v3/order` ou chaves de API no código. A configuração só aceita `mode = "paper"`
e o ciclo aborta se a variável `INVESTIDOR_LIVE` (ou `INVESTIDOR_MODE != paper`) estiver definida.

Os **R$ 50** reservados **não são movimentados** durante o desenvolvimento nem a simulação.

## Processo exigido antes de qualquer integração real

Nada abaixo é feito sem a sua autorização expressa e por escrito, dada nesta conversa/projeto, para uma plataforma específica.

1. **Elegibilidade legal e de idade (verificação manual, sua):** idade mínima da plataforma (em geral 18 anos), cadastro/KYC aprovado, regras de custódia e de tributação aplicáveis ao seu caso. Eu não presumo nada disso.
2. **Critérios objetivos medidos pelo sistema** (painel → *Estudo → Porta para dinheiro real*): ≥ 180 dias de paper trading; drawdown máximo < 20 %; evidência estatística (DSR ≥ 0,95); sem alertas críticos de dados em 30 dias; ativos viáveis para o capital.
3. **Autorização expressa** do titular, informando plataforma e valor.
4. **Só então**, implementação *nova* e revisada de um conector, com as travas abaixo desde a primeira linha.

## Travas obrigatórias de qualquer conector futuro
- **Sem alavancagem, sem empréstimo, sem margem, sem derivativos, sem venda a descoberto, sem martingale** (o motor atual já impede: caixa nunca negativo, posição nunca negativa, pesos limitados a 100 %).
- **Saldo nunca negativo.**
- **Sem saques automáticos** e sem permissão de saque na chave de API (chave só de leitura + negociação spot, restrita por IP quando possível).
- **Aporte único de R$ 50:** o sistema não pode pedir nem aceitar depósitos adicionais.
- **Reserva financeira preservada:** parte do valor permanece fora do mercado; ordem mínima e custos (taxas, spread, IOF/câmbio) calculados *antes* de operar; abaixo do mínimo da plataforma, não opera.
- **Impostos:** o sistema não os calcula; o titular é responsável (há regras de isenção/alíquota que dependem do tipo de ativo e do volume — confirmar com fonte oficial/contador).
- **Interrupção automática** ao atingir limites de risco (já existe em paper: −25 % desde o pico) e *kill switch* manual no painel.
- **Confirmação humana** para ligar o modo real; segredos apenas em *GitHub Secrets*, nunca no repositório.

## O que pode dar errado com dinheiro real (e não existe em simulação)
Rejeição de ordens, preenchimento parcial, spreads maiores que o modelado, indisponibilidade da corretora, erros de câmbio, taxa mínima fixa, impostos, e **comportamento humano** (intervir no pânico). Com R$ 50, custos fixos e lotes mínimos podem consumir uma fração relevante do capital.

**Não há promessa de retorno positivo, de lucro diário nem de sustentabilidade permanente.**
