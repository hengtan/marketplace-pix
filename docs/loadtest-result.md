# Resultado do teste de carga

Gerado por `scripts/loadtest.py` contra o gateway (porta 18000 de uma stack Docker paralela), 20 conexões
simultâneas por 30 s em cada rodada. Mistura de requisições: 40% listagem de produtos, 20% produto por slug,
10% categorias, 20% estoque, 10% criação de pedido (com `Idempotency-Key`). O resultado completo está em
`docs/loadtest-result.json`.

Como reproduzir:

```
backend/gateway/.venv/bin/python scripts/loadtest.py --base http://localhost:8000 --duration 30 --concurrency 20
```

## Resultados

Latências em milissegundos, calculadas sobre as respostas que não foram 429.

| Rodada | Requisições | req/s | p50 | p95 | p99 | máx | 429 | Erros (5xx e rede) |
|---|---|---|---|---|---|---|---|---|
| A1 (limites altos) | 4590 | 150.8 | 76.5 | 432.9 | 844.6 | 1371.1 | 0.0% | 0.0% |
| A2 (limites altos) | 3287 | 109.1 | 103.9 | 618.6 | 1153.7 | 2530.5 | 0.0% | 0.0% |
| A3 (limites altos) | 3682 | 122.2 | 96.1 | 535.3 | 935.5 | 2374.9 | 0.0% | 0.0% |
| B (limites padrão) | 4818 | 157.6 | 78.7 | 486.3 | 918.8 | 1263.4 | 58.95% | 0.0% |

- **A1 a A3:** limites do gateway elevados (`RATE_LIMIT_PER_MINUTE=100000000`), para medir a capacidade.
  Três rodadas seguidas porque o ambiente é ruidoso (veja a ressalva).
- **B:** limites padrão (600 por minuto por rota, 120 para `ordering`), com os baldes do Redis zerados antes.
  Cerca de 58.95% das requisições receberam 429 com `Retry-After`, e **nenhuma** gerou erro 5xx:
  o excesso foi recusado de forma controlada, sem derrubar o gateway.

Por endpoint na rodada B (as respostas 429 ficam de fora):

| Endpoint | Requisições | p50 | p95 | p99 |
|---|---|---|---|---|
| categories | 456 | 72.7 | 741.9 | 1104.7 |
| create_order | 521 | 83.7 | 524.2 | 776.2 |
| list_products | 1932 | 93.4 | 446.6 | 765.0 |
| product_by_slug | 961 | 87.5 | 501.8 | 676.0 |
| stock | 948 | 63.3 | 431.2 | 957.9 |

## Leitura

- Zero erros 5xx e zero falhas de rede em todas as rodadas, inclusive sob o limite.
- O gateway roda com 1 processo uvicorn e ficou perto de 100% de CPU durante a carga: ele é o gargalo
  desta medição, não o catálogo. Escalar horizontalmente (mais réplicas) é seguro porque o limite está no
  Redis e é compartilhado.
- O limite por rota funciona de forma independente: `ordering` (120 por minuto) começa a recusar muito antes
  de `catalog` e `inventory` (600 por minuto cada).

## Ressalvas

- Máquina compartilhada: durante as rodadas o load average do host passou de 30 (outros containers e
  processos), então a variação entre A1, A2 e A3 (109 a 151 req/s) é mais ruído do ambiente que
  característica do sistema. Os números servem para comparar versões na mesma máquina, não como capacidade absoluta.
- Cliente e servidor no mesmo host disputam CPU.
- A stack medida tem catalog, inventory, ordering, payments e ledger. Notifications e assistant não
  estavam no ar.
