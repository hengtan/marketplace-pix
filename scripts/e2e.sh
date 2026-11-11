#!/usr/bin/env bash
# Teste de ponta a ponta pelo gateway. Sai com código diferente de zero se algo falhar.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/.."
ENV_FILE=${ENV_FILE:-.env}
G=${GATEWAY:-http://localhost:8000/api}
M=${MAILPIT:-http://localhost:8025/api/v1}
PAYMENTS=${PAYMENTS_DIRECT:-http://localhost:8002}
SEED_PASSWORD=${IDENTITY_SEED_PASSWORD:-$(grep -E '^IDENTITY_SEED_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)}
source "$HERE/e2e-lib.sh"

RUN=$RANDOM$RANDOM
EMAIL="e2e.$RUN@example.com"
PASSWORD="E2e-senha-$RUN-segura"
CORDA=$(uuid5 product corda-pular-speed); GPS=$(uuid5 product relogio-gps-trail)
TRILHA=$(uuid5 merchant trilha-sports); AURORA=$(uuid5 merchant aurora-tech)
stock() { curl -s "$G/inventory/stock/$1" -H "$(auth "$MERCHANT_TOKEN")" | jget "'%s/%s' % (d['available'], d['reserved'])"; }
chat() { curl -s -X POST "$G/assistant/chat" -H 'content-type: application/json' ${2:+-H "$(auth "$2")"} -d "{\"message\":\"$1\"}" | jget "d['answer']"; }

echo "== 1. Saúde"
check "gateway agrega todos os serviços (inclui identity)" "$(curl -s "$G/health" | jget "d['status']")" "ok"

echo "== 2. Catálogo (público, sem token)"
check "busca sem acento acha Luminária" "$(curl -s "$G/catalog/products?q=luminaria" | jget "d['items'][0]['name']")" "Luminária Arco Dourado"
check "catálogo tem 24 produtos" "$(curl -s "$G/catalog/products?page_size=48" | jget "d['total']")" "24"

echo "== 3. Identidade"
REG=$(curl -s -X POST "$G/auth/register" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"name\":\"Teste E2E\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$REG" | jget "d['access_token']"); REFRESH=$(echo "$REG" | jget "d['refresh_token']"); CUST=$(echo "$REG" | jget "d['user']['id']")
check "registro devolve access token JWT" "$(echo "$TOKEN" | awk -F. '{print NF}')" "3"
check "e-mail repetido é recusado (409)" "$(status -X POST "$G/auth/register" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"name\":\"X\",\"password\":\"$PASSWORD\"}")" "409"
WRONG_LOGIN="{\"email\":\"$EMAIL\",\"password\":\"errada-errada\"}"
check "senha errada é recusada (401)" "$(status -X POST "$G/auth/login" -H 'content-type: application/json' -d "$WRONG_LOGIN")" "401"
BACKOFF=$(curl -s -o /dev/null -w '%{http_code}' -D "$CODE_FILE.h" -X POST "$G/auth/login" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
check "nova tentativa logo após a falha recebe 429 (espera progressiva)" "$BACKOFF" "429"
check "o 429 traz Retry-After" "$(tr 'A-Z' 'a-z' < "$CODE_FILE.h" | grep -c '^retry-after:')" "1"
rm -f "$CODE_FILE.h"
sleep 2.5
check "GET /auth/me devolve o usuário do token" "$(curl -s "$G/auth/me" -H "$(auth "$TOKEN")" | jget "d['email']")" "$EMAIL"
check "token adulterado é recusado (401)" "$(status "$G/auth/me" -H "$(auth "${TOKEN%?}x")")" "401"
check "sem token em rota protegida (401)" "$(status "$G/auth/me")" "401"
ROT=$(curl -s -X POST "$G/auth/refresh" -H 'content-type: application/json' -d "{\"refresh_token\":\"$REFRESH\"}")
NEWREFRESH=$(echo "$ROT" | jget "d['refresh_token']")
check "refresh rotaciona o token" "$([ -n "$NEWREFRESH" ] && [ "$NEWREFRESH" != "$REFRESH" ] && echo yes)" "yes"
check "reuso do refresh antigo é detectado (401)" "$(status -X POST "$G/auth/refresh" -H 'content-type: application/json' -d "{\"refresh_token\":\"$REFRESH\"}")" "401"
check "reuso derruba a família: o refresh novo também morre (401)" "$(status -X POST "$G/auth/refresh" -H 'content-type: application/json' -d "{\"refresh_token\":\"$NEWREFRESH\"}")" "401"
TOKEN=$(login "$EMAIL" "$PASSWORD")
check "login volta a funcionar" "$(echo "$TOKEN" | awk -F. '{print NF}')" "3"
check "cabeçalho X-User-Id forjado é ignorado (anônimo, 401)" "$(status "$G/ledger/reconciliation" -H "X-User-Id: $CUST" -H 'X-User-Roles: admin')" "401"
MERCHANT_TOKEN=$(login "trilha-sports@marketplace-pix.local" "$SEED_PASSWORD")
ADMIN_TOKEN=$(login "admin@marketplace-pix.local" "$SEED_PASSWORD")
check "lojista (seed) autenticou" "$(echo "$MERCHANT_TOKEN" | awk -F. '{print NF}')" "3"
check "admin (seed) autenticou" "$(echo "$ADMIN_TOKEN" | awk -F. '{print NF}')" "3"

echo "== 4. Autorização e multi-tenant"
check "ledger sem token (401)" "$(status "$G/ledger/merchants/$TRILHA/summary")" "401"
check "cliente não lê ledger (403)" "$(status "$G/ledger/merchants/$TRILHA/summary" -H "$(auth "$TOKEN")")" "403"
check "lojista lê o próprio ledger (200)" "$(status "$G/ledger/merchants/$TRILHA/summary" -H "$(auth "$MERCHANT_TOKEN")")" "200"
check "lojista não lê o ledger de outro lojista (403)" "$(status "$G/ledger/merchants/$AURORA/summary" -H "$(auth "$MERCHANT_TOKEN")")" "403"
check "lojista não lê conta de outro lojista (403)" "$(status "$G/ledger/accounts/merchant:$AURORA/entries" -H "$(auth "$MERCHANT_TOKEN")")" "403"
check "lojista não roda conciliação (403)" "$(status "$G/ledger/reconciliation" -H "$(auth "$MERCHANT_TOKEN")")" "403"
check "admin roda conciliação (200)" "$(status "$G/ledger/reconciliation" -H "$(auth "$ADMIN_TOKEN")")" "200"
check "estoque sem token (401)" "$(status -X PUT "$G/inventory/stock/$CORDA" -H 'content-type: application/json' -d '{"available":25}')" "401"
check "cliente não altera estoque (403)" "$(status -X PUT "$G/inventory/stock/$CORDA" -H 'content-type: application/json' -H "$(auth "$TOKEN")" -d '{"available":25}')" "403"
check "lojista não altera estoque de outro lojista (403)" "$(status -X PUT "$G/inventory/stock/$(uuid5 product fone-bluetooth-nova)" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"available":0}')" "403"
check "lojista lista o próprio estoque (8 produtos)" "$(curl -s "$G/inventory/stock/mine" -H "$(auth "$MERCHANT_TOKEN")" | jget "len(d)")" "8"

summary() { curl -s "$G/ledger/merchants/$TRILHA/summary?days=1" -H "$(auth "$MERCHANT_TOKEN")"; }

echo "== 5. Pedido feliz (preço vem do catálogo mesmo o cliente mandando 1 centavo)"
curl -s -X PUT "$G/inventory/stock/$CORDA" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"available":25}' >/dev/null
sleep 1
S0=$(stock "$CORDA"); A0=${S0%/*}; R0=${S0#*/}
BEFORE=$(summary); B_GROSS=$(echo "$BEFORE" | jget "d['gross_sales_cents']"); B_FEES=$(echo "$BEFORE" | jget "d['platform_fees_cents']")
KEY="e2e-$RUN"
ORDER_JSON=$(post_order "$CORDA" 2 "$CUST" "$EMAIL" "$KEY" "$TOKEN"); check "POST /orders devolve 201" "$(cat "$CODE_FILE")" "201"
ORDER=$(echo "$ORDER_JSON" | jget "d['id']")
check "total = 2 x R\$ 49,90 (preço do catálogo)" "$(curl -s "$G/orders/$ORDER" -H "$(auth "$TOKEN")" | jget "d['total_cents']")" "9980"
REPLAY=$(post_order "$CORDA" 2 "$CUST" "$EMAIL" "$KEY" "$TOKEN" | jget "d['id']"); check "mesma Idempotency-Key devolve o mesmo pedido" "$REPLAY" "$ORDER"
wait_for "cobrança PIX criada" "curl -s -o /dev/null -w '%{http_code}' $G/payments/by-order/$ORDER -H 'Authorization: Bearer $TOKEN'" "200"
CH=$(curl -s "$G/payments/by-order/$ORDER" -H "$(auth "$TOKEN")" | jget "d['psp_charge_id']")
wait_for "estoque reservado (-2 livres, +2 reservados)" "stock $CORDA" "$((A0-2))/$((R0+2))"
check "webhook sem assinatura é recusado (401)" "$(status -X POST "$PAYMENTS/webhooks/psp" -d "{\"event\":\"charge.paid\",\"charge_id\":\"$CH\"}")" "401"
check "pedido segue PENDING antes do pagamento" "$(curl -s "$G/orders/$ORDER" -H "$(auth "$TOKEN")" | jget "d['status']")" "PENDING"
curl -s -X POST "$G/payments/dev/psp/charges/$CH/pay" -H "$(auth "$TOKEN")" >/dev/null
wait_for "pedido vira PAID" "curl -s $G/orders/$ORDER -H 'Authorization: Bearer $TOKEN' | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "PAID"
wait_for "venda confirmada (reservas voltam, livres ficam)" "stock $CORDA" "$((A0-2))/$R0"
sleep 3
AFTER=$(summary)
check "ledger: vendas brutas +9980" "$(( $(echo "$AFTER" | jget "d['gross_sales_cents']") - B_GROSS ))" "9980"
check "ledger: taxa da plataforma +998 (10%)" "$(( $(echo "$AFTER" | jget "d['platform_fees_cents']") - B_FEES ))" "998"
check "ledger: conciliação balanceada" "$(curl -s "$G/ledger/reconciliation" -H "$(auth "$ADMIN_TOKEN")" | jget "d['balanced']")" "True"
wait_for "3 e-mails enviados" "curl -s '$M/search?query=to:$EMAIL' | python3 -c \"import sys,json;print(json.load(sys.stdin)['messages_count'])\"" "3" 40
check "API de notificações lista os 3 como SENT" "$(curl -s "$G/notifications" -H "$(auth "$TOKEN")" | jget "sorted(set(n['status'] for n in d['items']))")" "['SENT']"
check "lojista vê o pedido na própria fila" "$(curl -s "$G/orders/merchant" -H "$(auth "$MERCHANT_TOKEN")" | jget "str(any(o['id']=='$ORDER' for o in d['items']))")" "True"
check "lojista de outra loja não vê o pedido" "$(curl -s "$G/orders/merchant" -H "$(auth "$(login "aurora-tech@marketplace-pix.local" "$SEED_PASSWORD")")" | jget "str(any(o['id']=='$ORDER' for o in d['items']))")" "False"

echo "== 6. Isolamento entre usuários (BOLA/IDOR)"
OTHER_EMAIL="e2e.other.$RUN@example.com"
OTHER=$(curl -s -X POST "$G/auth/register" -H 'content-type: application/json' -d "{\"email\":\"$OTHER_EMAIL\",\"name\":\"Outro\",\"password\":\"$PASSWORD\"}" | jget "d['access_token']")
check "outro usuário não lê o pedido (404)" "$(status "$G/orders/$ORDER" -H "$(auth "$OTHER")")" "404"
check "outro usuário não lê o pagamento (404)" "$(status "$G/payments/by-order/$ORDER" -H "$(auth "$OTHER")")" "404"
check "pedido de outro não aparece na minha lista" "$(curl -s "$G/orders" -H "$(auth "$OTHER")" | jget "d['total']")" "0"
check "outro usuário não lista meus pedidos por customer_id (403)" "$(status "$G/orders?customer_id=$CUST" -H "$(auth "$OTHER")")" "403"
check "outro usuário não lê minhas notificações (403)" "$(status "$G/notifications?customer_id=$CUST" -H "$(auth "$OTHER")")" "403"
check "dono continua lendo o pedido (200)" "$(status "$G/orders/$ORDER" -H "$(auth "$TOKEN")")" "200"

echo "== 7. Checkout de convidado continua funcionando"
GUEST=$(python3 -c 'import uuid;print(uuid.uuid4())')
GORDER=$(post_order "$CORDA" 1 "$GUEST" "guest.$RUN@example.com" "e2e-guest-$RUN" | jget "d['id']"); check "convidado cria pedido (201)" "$(cat "$CODE_FILE")" "201"
check "convidado lê o próprio pedido pelo id (200)" "$(status "$G/orders/$GORDER")" "200"
PCODE=$(status "$G/payments/by-order/$GORDER")
check "pagamento logo após criar o pedido é 200 ou 202, nunca 404" "$([ "$PCODE" = 200 ] || [ "$PCODE" = 202 ] && echo ok)" "ok"
check "pagamento de pedido que não existe é 404" "$(status "$G/payments/by-order/$(python3 -c 'import uuid;print(uuid.uuid4())')")" "404"
check "pedido de convidado não aparece na conta de ninguém" "$(curl -s "$G/orders" -H "$(auth "$TOKEN")" | jget "str(any(o['id']=='$GORDER' for o in d['items']))")" "False"

echo "== 8. Sem estoque cancela pedido e cobrança"
OUT=$(post_order "$GPS" 50 "$CUST" "$EMAIL" "e2e-oos-$RUN" "$TOKEN"); ORDER2=$(echo "$OUT" | jget "d['id']"); check "pedido de 50 unidades aceito (201)" "$(cat "$CODE_FILE")" "201"
wait_for "pedido cancelado por falta de estoque" "curl -s $G/orders/$ORDER2 -H 'Authorization: Bearer $TOKEN' | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d['status'],d['cancel_reason'])\"" "CANCELLED out of stock"
wait_for "cobrança cancelada" "curl -s $G/payments/by-order/$ORDER2 -H 'Authorization: Bearer $TOKEN' | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "CANCELLED"
CH2=$(curl -s "$G/payments/by-order/$ORDER2" -H "$(auth "$TOKEN")" | jget "d['psp_charge_id']")
check "pagar PIX cancelado é recusado (409)" "$(status -X POST "$G/payments/dev/psp/charges/$CH2/pay" -H "$(auth "$TOKEN")")" "409"

echo "== 9. Validações"
post_order "$(python3 -c 'import uuid;print(uuid.uuid4())')" 1 "$CUST" "$EMAIL" "e2e-unk-$RUN" "$TOKEN" >/dev/null; check "produto inexistente (422)" "$(cat "$CODE_FILE")" "422"
check "sem Idempotency-Key (400)" "$(status -X POST "$G/orders" -H 'content-type: application/json' -H "$(auth "$TOKEN")" -d "{\"customer_name\":\"Teste E2E\",\"customer_email\":\"$EMAIL\",\"items\":[{\"product_id\":\"$CORDA\",\"quantity\":1}]}")" "400"

echo "== 10. Estoque, cabeçalhos, limite de corpo e revogação"
check "estoque público não expõe reserved" "$(curl -s "$G/inventory/stock/$CORDA" | jget "'reserved' in d")" "False"
check "estoque público lista só available" "$(curl -s "$G/inventory/stock?product_ids=$CORDA" | jget "sorted(d[0])")" "['available', 'product_id']"
check "lojista dono vê reserved" "$(curl -s "$G/inventory/stock/$CORDA" -H "$(auth "$MERCHANT_TOKEN")" | jget "'reserved' in d")" "True"
check "lojista de outra loja não vê reserved" "$(curl -s "$G/inventory/stock/$CORDA" -H "$(auth "$(login "aurora-tech@marketplace-pix.local" "$SEED_PASSWORD")")" | jget "'reserved' in d")" "False"
HDRS=$(curl -sI "$G/catalog/categories" | tr -d '\r' | tr 'A-Z' 'a-z')
check "cabeçalho X-Content-Type-Options: nosniff" "$(echo "$HDRS" | grep -c '^x-content-type-options: nosniff')" "1"
check "cabeçalho Referrer-Policy" "$(echo "$HDRS" | grep -c '^referrer-policy:')" "1"
check "cabeçalho Permissions-Policy" "$(echo "$HDRS" | grep -c '^permissions-policy:')" "1"
check "cabeçalho Cross-Origin-Resource-Policy" "$(echo "$HDRS" | grep -c '^cross-origin-resource-policy:')" "1"
check "HSTS desligado por padrão em desenvolvimento" "$(echo "$HDRS" | grep -c '^strict-transport-security:')" "0"
BIG=$(mktemp); head -c 2000000 /dev/zero | tr '\0' 'a' > "$BIG"
check "corpo de 2 MB é recusado (413)" "$(status -X POST "$G/orders" -H 'content-type: application/json' -H 'Idempotency-Key: big' --data-binary "@$BIG")" "413"
rm -f "$BIG"
LOGIN2=$(curl -s -X POST "$G/auth/login" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
T2=$(echo "$LOGIN2" | jget "d['access_token']"); R2=$(echo "$LOGIN2" | jget "d['refresh_token']")
check "access token vale antes do logout" "$(status "$G/auth/me" -H "$(auth "$T2")")" "200"
curl -s -o /dev/null -X POST "$G/auth/logout" -H 'content-type: application/json' -d "{\"refresh_token\":\"$R2\"}"
REVOKED=no
for _ in 1 2 3 4 5; do
  [ "$(status "$G/auth/me" -H "$(auth "$T2")")" = 401 ] && { REVOKED=yes; break; }
  sleep 0.2
done
check "o mesmo access token recebe 401 em até 1 s depois do logout" "$REVOKED" "yes"
check "outro token da mesma conta segue valendo" "$(status "$G/auth/me" -H "$(auth "$TOKEN")")" "200"

echo "== 11. Assistente: identidade e eventos do catálogo"
check "dono pergunta pelo próprio pedido e vê o status" "$(chat "status do pedido $ORDER" "$TOKEN" | grep -c "Pedido\|pago")" "1"
check "outro usuário não vê o pedido pelo chat" "$(chat "status do pedido $ORDER" "$OTHER" | grep -c "Não encontrei")" "1"
check "anônimo não vê pedido de conta pelo chat" "$(chat "status do pedido $ORDER" | grep -c "Não encontrei")" "1"
check "pedido de convidado continua consultável por id" "$(chat "status do pedido $GORDER" | grep -c "Não encontrei")" "0"
OLD=$(curl -s "$G/catalog/products/$CORDA" | jget "d['price_cents']")
chat "quanto custa a corda de pular speed?" >/dev/null
chat "quanto custa a corda de pular speed?" >/dev/null
check "dono altera o preço pelo catálogo (200)" "$(status -X PATCH "$G/catalog/products/$CORDA" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"price_cents":5490}')" "200"
wait_for "assistente responde o preço novo sem reindexar" "chat 'quanto custa a corda de pular speed?' | grep -c '54,90'" "1" 40
check "lojista de outra loja não altera o preço (403)" "$(status -X PATCH "$G/catalog/products/$CORDA" -H 'content-type: application/json' -H "$(auth "$(login "aurora-tech@marketplace-pix.local" "$SEED_PASSWORD")")" -d '{"price_cents":1}')" "403"
curl -s -o /dev/null -X PATCH "$G/catalog/products/$CORDA" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d "{\"price_cents\":$OLD}"
wait_for "preço volta ao original no assistente" "chat 'quanto custa a corda de pular speed?' | grep -c '49,90'" "1" 40

echo "== 12. Ciclo de vida do lojista: do produto novo ao dinheiro no painel"
LN=$RANDOM$RANDOM
LNAME="Ciclo Teste $LN"
LCREATE=$(curl -s -w '\n%{http_code}' -X POST "$G/catalog/products" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" \
  -d "{\"name\":\"$LNAME\",\"description\":\"Produto criado pelo teste de ciclo de vida do lojista\",\"category\":\"esporte\",\"price_cents\":4990}")
check "lojista cria um produto (201)" "$(echo "$LCREATE" | tail -n1)" "201"
LPID=$(echo "$LCREATE" | sed '$d' | jget "d['id']"); LSLUG=$(echo "$LCREATE" | sed '$d' | jget "d['slug']")
wait_for "o inventário cria a linha de estoque sozinha, vazia" "curl -s '$G/inventory/stock/$LPID' | jget \"d['available']\"" "0" 40
L0=$(post_order "$LPID" 1 "$(python3 -c 'import uuid;print(uuid.uuid4())')" "ciclo0.$LN@example.com" "ciclo0-$LN"); L0CODE=$(cat "$CODE_FILE")
check "pedido de produto ainda sem estoque é aceito (201)" "$L0CODE" "201"
L0ID=$(echo "$L0" | jget "d['id']")
wait_for "e a saga o cancela por falta de estoque, antes de qualquer cobrança" "curl -s '$G/orders/$L0ID' | jget \"d['status']\"" "CANCELLED" 40
check "outro lojista não define o estoque do produto (403)" "$(status -X PUT "$G/inventory/stock/$LPID" -H 'content-type: application/json' -H "$(auth "$(login "aurora-tech@marketplace-pix.local" "$SEED_PASSWORD")")" -d '{"available":99}')" "403"
check "dono define o estoque em 30 (200)" "$(status -X PUT "$G/inventory/stock/$LPID" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"available":30}')" "200"
check "o produto aparece na vitrine por slug" "$(status "$G/catalog/products/slug/$LSLUG")" "200"
check "o produto aparece na busca" "$(curl -s "$G/catalog/products?q=Ciclo+Teste+$LN" | jget "len([p for p in d['items'] if p['slug']=='$LSLUG'])")" "1"
GROSS0=$(curl -s "$G/ledger/merchants/$TRILHA/summary?days=1" -H "$(auth "$MERCHANT_TOKEN")" | jget "d['gross_sales_cents']")
LCUST=$(python3 -c 'import uuid;print(uuid.uuid4())')
LORDER_BODY=$(post_order "$LPID" 2 "$LCUST" "ciclo.$LN@example.com" "ciclo-$LN")
check "convidado compra 2 unidades (201)" "$(cat "$CODE_FILE")" "201"
LORDER=$(echo "$LORDER_BODY" | jget "d['id']")
wait_for "o estoque reserva as 2 unidades" "curl -s '$G/inventory/stock/$LPID' | jget \"d['available']\"" "28" 30
wait_for "a cobrança PIX é criada" "curl -s '$G/payments/by-order/$LORDER' | jget \"d['status']\"" "PENDING" 30
LCHARGE=$(curl -s "$G/payments/by-order/$LORDER" | jget "d['psp_charge_id']")
check "convidado paga o próprio PIX sem login (200)" "$(status -X POST "$G/payments/dev/psp/charges/$LCHARGE/pay")" "200"
wait_for "o pedido fica PAID" "curl -s '$G/orders/$LORDER' | jget \"d['status']\"" "PAID" 40
wait_for "o pedido aparece na fila do lojista como PAID" "curl -s '$G/orders/merchant?page_size=50' -H '$(auth "$MERCHANT_TOKEN")' | jget \"[o['status'] for o in d['items'] if o['id']=='$LORDER'][0]\"" "PAID" 30
wait_for "o livro-razão credita a venda ao lojista (2 x R\$ 49,90)" "curl -s '$G/ledger/merchants/$TRILHA/summary?days=1' -H '$(auth "$MERCHANT_TOKEN")' | jget \"d['gross_sales_cents']-$GROSS0\"" "9980" 40
check "a venda definitiva mantém 28 em estoque" "$(curl -s "$G/inventory/stock/$LPID" | jget "d['available']")" "28"
check "dono altera o preço (200)" "$(status -X PATCH "$G/catalog/products/$LPID" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"price_cents":5990}')" "200"
check "o preço novo vale na hora na vitrine" "$(curl -s "$G/catalog/products/slug/$LSLUG" | jget "d['price_cents']")" "5990"
check "dono desativa o produto (204)" "$(status -X DELETE "$G/catalog/products/$LPID" -H "$(auth "$MERCHANT_TOKEN")")" "204"
check "o produto desativado some da vitrine (404)" "$(status "$G/catalog/products/slug/$LSLUG")" "404"
check "não dá para comprar um produto desativado (422)" "$(post_order "$LPID" 1 "$LCUST" "ciclo2.$LN@example.com" "ciclo2-$LN" >/dev/null; cat "$CODE_FILE")" "422"
check "outro lojista não reativa o produto (403)" "$(status -X POST "$G/catalog/products/$LPID/reactivate" -H "$(auth "$(login "aurora-tech@marketplace-pix.local" "$SEED_PASSWORD")")")" "403"
check "dono reativa o produto (200)" "$(status -X POST "$G/catalog/products/$LPID/reactivate" -H "$(auth "$MERCHANT_TOKEN")")" "200"
check "o produto reativado volta à vitrine com o preço novo" "$(curl -s "$G/catalog/products/slug/$LSLUG" | jget "d['price_cents']")" "5990"
check "reativar mantém o estoque que já existia" "$(curl -s "$G/inventory/stock/$LPID" | jget "d['available']")" "28"
wait_for "o assistente volta a conhecer o produto reativado" "curl -s -X POST '$G/assistant/chat' -H 'content-type: application/json' -d '{\"message\":\"$LNAME\"}' | grep -c 'Ciclo Teste $LN'" "1" 40
curl -s -o /dev/null -X DELETE "$G/catalog/products/$LPID" -H "$(auth "$MERCHANT_TOKEN")"

summary_result
