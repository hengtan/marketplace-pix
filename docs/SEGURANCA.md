# Segurança

Modelo de ameaças resumido (STRIDE), mapa do OWASP API Security Top 10 (2023) para o que foi feito, limitações
conhecidas e um roteiro de fala para entrevista. A decisão de arquitetura da identidade está em
`docs/adr/0001-identidade-como-servico.md`, e os contratos das rotas em `docs/CONTRATOS.md`.

## 1. Fronteiras de confiança

```
Internet ──► gateway ──► serviços (ordering, ledger, inventory, ...) ──► Postgres, Kafka
             │   ▲
             │   └── JWKS (chave pública) ◄── identity (chaves, senhas, refresh tokens)
             └── remove X-User-*, valida o JWT, assina a identidade que repassa
```

| Fronteira | Quem cruza | Controle |
|---|---|---|
| Internet → gateway | qualquer cliente | limite de requisições, CORS por origem, política por rota, JWT validado |
| gateway → serviço | só o gateway (mas as portas ficam publicadas no host) | identidade assinada com HMAC, presa ao `X-Request-Id` e a um carimbo de 60 s |
| serviço → serviço | `ordering` → `catalog`, `assistant` → outros | sem identidade do usuário; trata como anônimo, então só acessa o que é público |
| serviço → Kafka → serviço | eventos | eventos versionados, deduplicados por inbox, com golden files de contrato |
| PSP → payments | webhook | HMAC no corpo e reconsulta ao PSP antes de confirmar |

Segredos entram **só por variável de ambiente** (`INTERNAL_AUTH_SECRET`, `IDENTITY_SIGNING_KEY`,
`IDENTITY_SEED_PASSWORD`, `PSP_WEBHOOK_SECRET`, senhas do banco). Nada é commitado. Em desenvolvimento o
`scripts/up.sh` gera os valores no `.env` (ignorado pelo git) e o `identity` gera uma chave de assinatura
efêmera na subida. Fora de desenvolvimento, `ENVIRONMENT=production` exige a chave e o segredo, e o gateway se
recusa a subir sem `INTERNAL_AUTH_SECRET`.

## 2. STRIDE

| Ameaça | Onde | Exemplo | Mitigação | Evidência (teste) |
|---|---|---|---|---|
| **S**poofing | Gateway, cabeçalhos | cliente manda `X-User-Id: <admin>` | o gateway remove todos os `X-User-*`, `X-Auth-*` e `Authorization` do cliente e injeta a identidade assinada; serviço sem assinatura válida vê anônimo | `test_client_supplied_identity_headers_never_reach_upstreams`, `test_forged_and_replayed_identity_is_ignored` (ledger), `test_a_forged_identity_header_is_not_trusted` (ordering) |
| Spoofing | Tokens | `alg: none`, HS256 com a chave pública, `kid` desconhecido, token de outro emissor | algoritmo fixado em `EdDSA`, `iss`, `aud`, `exp` e `iat` obrigatórios, JWKS com recarga limitada | `test_invalid_tokens_are_rejected_with_401` (10 variações) |
| Spoofing | Login | enumerar e-mails pelo tempo ou pela mensagem | mesma resposta e mesmo trabalho de hash para e-mail inexistente, senha errada e conta bloqueada | `test_unknown_user_costs_the_same_hash_work`, `test_login_failures_do_not_reveal_whether_the_email_exists` |
| **T**ampering | Identidade interna | alterar o papel no caminho gateway → serviço | HMAC sobre usuário, papéis, escopos, lojista, carimbo e request id | `test_tampered_roles_are_rejected`, `test_signature_is_bound_to_the_request` |
| Tampering | Pedido | cliente mandar preço ou `merchant_id` | preço e lojista vêm do catálogo; o corpo ignora o que não declara | `test_price_sent_by_the_client_is_ignored` |
| Tampering | Eventos | produtor mudar o formato sem aviso | golden files e `schema_version` | `test_a_producer_that_adds_a_field_without_a_new_version_breaks_the_contract` |
| Tampering | Webhook do PSP | confirmar pagamento forjado | HMAC no corpo e reconsulta ao PSP (fail-closed) | e2e: webhook sem assinatura devolve 401 |
| **R**epudiation | Pagamento tardio, timeout | "o pedido foi cancelado e ninguém sabe por quê" | tabela `order_audit` (timeout, pagamento tardio) com chave única, eventos no outbox, métricas e `request_id` nos logs | `test_payment_after_the_timeout_is_refunded_not_applied` |
| Repudiation | Sessões | usuário nega um login | refresh tokens por família com data de uso e revogação; reuso é logado com usuário e família | `test_reusing_a_rotated_token_revokes_the_whole_family` |
| **I**nformation disclosure | Pedidos | usuário B lê o pedido de A | autorização por objeto no serviço; pedido alheio responde `404` igual ao inexistente | `test_bola_user_b_cannot_read_user_a_order`, `test_a_nonexistent_order_looks_the_same_as_someone_elses` |
| Information disclosure | Multi-tenant | lojista A lê o ledger ou o estoque de B | `merchant_id` vem do token, nunca do cliente; ledger, estoque e fila de pedidos conferem o dono | `test_merchants_are_isolated_in_the_summary`, `test_merchant_updates_only_their_own_products`, `test_merchant_sees_only_orders_and_items_of_their_own_store` |
| Information disclosure | Credenciais | vazamento do banco | senhas em argon2id, refresh tokens só como SHA-256, JWKS sem material privado | `test_argon2id_hashes_verify_and_are_salted`, `test_jwks_never_exposes_private_material` |
| **D**enial of service | Gateway | enxurrada de requisições | limite por IP, paginação limitada, `page_size` máximo, itens e quantidade limitados | `test_rate_limit_returns_429_with_retry_after` |
| Denial of service | Login | senha enorme para custar CPU de argon2 | senha de até 128 caracteres; hash fora do loop de eventos; bloqueio por conta | `test_weak_passwords_are_rejected` |
| Denial of service | JWKS | inundar o gateway com `kid` falsos para forçar chamadas ao identity | no máximo uma recarga a cada 10 s | `test_jwks_refresh_is_throttled_against_unknown_kid_floods` |
| Denial of service | Banco | tabelas de apoio crescendo sem fim | retenção em lotes com `SKIP LOCKED` | `test_writers_are_not_blocked_while_a_big_cleanup_runs` |
| **E**levation of privilege | Registro | `roles: ["admin"]` no cadastro | o cadastro só cria `customer`; lojista e admin só por `POST /auth/admin/users` | `test_register_ignores_a_client_supplied_role` |
| Elevation of privilege | Rotas | cliente chamando rota de lojista | política por método, caminho e escopo no gateway, reaplicada no serviço | `test_role_based_authorization` (15 casos), `test_every_endpoint_requires_authentication` |
| Elevation of privilege | Refresh | roubo do refresh token | rotação e detecção de reuso revogam a família; prazo absoluto de 30 dias | `test_concurrent_refresh_with_one_token_has_a_single_winner` |

## 3. OWASP API Security Top 10 (2023)

| # | Risco | O que foi feito | Lacuna honesta |
|---|---|---|---|
| API1 | Autorização quebrada em nível de objeto (BOLA/IDOR) | Pedido pertence ao `owner_id` do token; `GET /orders/{id}` de pedido alheio dá `404`; listagem só devolve os pedidos do token; pagamento só responde a quem vê o pedido (o gateway consulta o ordering com a identidade do chamador); ledger e estoque conferem o lojista; testes de BOLA em memória, com Postgres real e no e2e (`scripts/e2e.sh`, seção 6) | Pedido de **convidado** é lido por quem tem o id (uuid v4, não adivinhável). `GET /notifications/{id}/preview` exige token mas não confere o dono |
| API2 | Autenticação quebrada | argon2id, JWT `EdDSA` de 10 minutos com `kid` e JWKS, algoritmo fixado, refresh opaco e rotativo com detecção de reuso, prazo absoluto de sessão, bloqueio por conta (5 falhas, 15 min), respostas e tempo iguais para e-mail inexistente, `Cache-Control: no-store` nos tokens | Sem MFA, sem verificação de e-mail, sem checagem de senha vazada, sem limite por e-mail além do bloqueio da conta |
| API3 | Autorização quebrada em nível de propriedade | Esquemas de entrada fechados (o cadastro não aceita papéis, o pedido não aceita preço nem lojista); a visão do lojista é um modelo próprio, sem e-mail do cliente e só com os itens dele | Os esquemas ignoram campos extras em vez de recusá-los |
| API4 | Consumo irrestrito de recursos | Limite por IP no gateway, `page_size` máximo, até 50 itens e 99 unidades por pedido, senha até 128 caracteres, timeout e `502/504` nos upstreams, retenção em lotes para as tabelas de apoio | Sem limite de tamanho de corpo no gateway; o limite por IP é em memória, por instância |
| API5 | Autorização quebrada em nível de função (BFLA) | Matriz de rotas por método e escopo no gateway (`gateway/auth/policy.py`), rota desconhecida exige token, rotas de administração (`/auth/admin`, reindexar o assistente, conciliação) só com escopo de admin | A política vive no código do gateway, não em um arquivo declarativo externo |
| API6 | Acesso irrestrito a fluxos de negócio sensíveis | Idempotência no pedido, reserva de estoque com TTL e cancelamento por timeout da saga (sem acaparar estoque), pagamento tardio reembolsado, checkout de convidado desligável (`ALLOW_GUEST_CHECKOUT=false`) | Sem proteção contra cadastro em massa (captcha, prova de trabalho) |
| API7 | SSRF | O gateway só fala com a lista fixa de upstreams da configuração; nenhum endpoint recebe URL do cliente | O assistente tem ferramentas que chamam outros serviços (fora do escopo desta frente) |
| API8 | Configuração incorreta de segurança | CORS por origem, rotas de desenvolvimento desligadas por padrão e, quando ligadas, autenticadas, o gateway se recusa a subir sem segredo interno, a produção exige chave de assinatura, segredos só por ambiente, erros sem detalhes internos | Sem cabeçalhos de segurança de resposta (HSTS, CSP, `X-Content-Type-Options`); portas dos serviços publicadas no host em desenvolvimento (por isso a identidade é assinada) |
| API9 | Gestão inadequada de inventário | Uma única tabela de rotas e portas (`docs/CONTRATOS.md`), eventos com versão e arquivos golden, matriz de acesso documentada, rotas de desenvolvimento marcadas | Sem descoberta automática de rotas expostas (um `openapi` consolidado) |
| API10 | Consumo inseguro de APIs | Preço e lojista vêm do catálogo e não do cliente, webhook do PSP com HMAC e reconsulta, eventos validados por modelo e com retry e DLQ, contrato de evento testado dos dois lados | O catálogo e o PSP simulado são confiáveis por construção neste estudo |

## 4. Como a autorização está montada

1. **Gateway** (`backend/gateway/src/gateway/auth/`): `policy.py` diz, por método e caminho, se a rota é pública,
   opcional ou obrigatória e qual escopo exige. `verifier.py` valida o JWT. `guard.py` aplica a política, força
   `customer_id` nas notificações, consulta o ordering para proteger o pagamento e assina a identidade.
2. **Biblioteca** (`marketplace_common.security`): `Principal`, papéis, escopos e a assinatura HMAC. Quem
   verifica é a dependência `PrincipalResolver`, igual em todos os serviços.
3. **Serviços**: cada um reaplica a regra de objeto que só ele sabe (dono do pedido, lojista do ledger, lojista
   do produto). Sem identidade assinada, a chamada é anônima.

Escopos nascem dos papéis (`customer`, `merchant`, `admin`) na emissão do token. O lojista carrega o
`merchant_id` na claim, e é ele que vira o tenant em todas as consultas.

## 5. Operação

| Tema | Como |
|---|---|
| Rotação da chave de assinatura | publicar a chave nova em `IDENTITY_SIGNING_KEY` e a pública antiga em `IDENTITY_RETIRED_PUBLIC_KEYS`; o JWKS expõe as duas, e os tokens antigos valem até expirar (10 min) |
| Gerar uma chave | `python -m identity.keys_cli` imprime um PEM Ed25519 em uma linha, pronto para a variável de ambiente |
| Rotação do `INTERNAL_AUTH_SECRET` | trocar em todos os serviços e no gateway; a identidade assinada dura 60 s, então a janela de incompatibilidade é curta |
| Revogar um usuário | `disabled = true` bloqueia login e refresh; o access token restante expira em até 10 min |
| Investigar reuso de refresh token | métrica `identity_refresh_total{result="reuse"}` e o log `refresh token reuse detected` com usuário e família |
| Investigar pagamento tardio | métrica `marketplace_saga_late_payments_total`, tabela `order_audit` e o evento `PaymentRefundRequested` |

## 6. Limitações conhecidas

- O access token não é revogável antes de expirar (10 minutos): é o custo de validar sem consultar o banco.
- O refresh token vai no corpo da resposta. Um front de produção deveria guardá-lo em cookie `HttpOnly` com um
  BFF, e o access token só em memória.
- O assistente (RAG) chama o ordering sem identidade e por isso não enxerga pedidos de contas autenticadas.
- O limite de requisições é em memória e por instância, e o cadastro em massa não é combatido.
- O checkout de convidado depende do id do pedido como segredo de acesso.
- Segredos em variáveis de ambiente são o mínimo aceitável; em produção valem um cofre e rotação automática.

## 7. Roteiro de fala para entrevista

**"Como você cuidou de segurança nesse marketplace?"**

> Comecei pelo modelo de ameaças, em STRIDE, e fui fechando as lacunas na ordem do risco. O primeiro problema
> era que nada tinha dono: qualquer um lia o pedido de qualquer um e mexia no estoque. Criei um serviço de
> identidade separado, porque quero que o proxy de borda tenha só a chave pública e não guarde senha nem chave
> privada. Ele usa argon2id, emite um JWT curto assinado com EdDSA e publica as chaves em um JWKS, e o refresh
> token é opaco, rotativo e com detecção de reuso: se alguém reapresenta um token já usado, a sessão inteira é
> revogada.
>
> O gateway valida o token, **apaga** qualquer cabeçalho de identidade que o cliente mandou e injeta o dele,
> assinado com HMAC e preso ao request id. Isso importa porque as portas dos serviços também ficam abertas no
> ambiente local, então eu não posso confiar no cabeçalho só porque ele "veio do gateway". Cada serviço reaplica
> a regra de objeto: o pedido é do dono, o ledger e o estoque são do lojista do token. O `merchant_id` vem da
> claim, nunca de um parâmetro, e por isso o isolamento entre lojistas é testado com dois lojistas reais.
>
> Para BOLA eu respondo `404` para o pedido alheio, igual ao inexistente, para não vazar que ele existe. Mantive o
> checkout de convidado porque a vitrine pública dependia dele, e o deixei desligável por configuração.

**Perguntas de acompanhamento**

- *Por que EdDSA e não HS256?* Porque quem valida (gateway) não precisa poder emitir. Com chave assimétrica o
  gateway só tem a pública, e a rotação é por `kid` no JWKS.
- *Como você impede `alg: none` e confusão de algoritmo?* Fixo `EdDSA` na verificação e exijo `kid`, `exp`,
  `iss` e `aud`. Há teste com `none`, com HS256 assinado com a chave pública e com `kid` desconhecido.
- *Refresh token roubado?* A rotação faz o ladrão e o dono disputarem o mesmo token. Quem chegar segundo
  dispara a revogação da família, e a sessão acaba nos dois. Há um teste de concorrência com seis requisições.
- *O que ficou de fora?* MFA, cookie `HttpOnly` por um BFF, revogação imediata do access token, proteção de
  cadastro em massa e cabeçalhos de segurança. Estão listados acima, com o motivo.
- *Como provar que o isolamento funciona?* Testes por camada (memória, Postgres real) e o e2e, que cria dois
  usuários e dois lojistas e tenta ler o que não é deles.
