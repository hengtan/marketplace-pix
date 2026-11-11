#!/usr/bin/env bash
# Teste de ponta a ponta pelo gateway. Sai com código diferente de zero se algo falhar.
set -uo pipefail
cd "$(dirname "$0")/.."
G=${GATEWAY:-http://localhost:8000/api}
M=${MAILPIT:-http://localhost:8025/api/v1}
PAYMENTS=${PAYMENTS_DIRECT:-http://localhost:8002}
PASS=0; FAIL=0
CODE_FILE=$(mktemp); trap 'rm -f "$CODE_FILE"' EXIT

ok()   { PASS=$((PASS+1)); printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFALHA\033[0m %s (obtido: %s)\n' "$1" "$2"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$2 | esperado: $3"; fi; }
jget() { python3 -c "import sys,json
d=json.load(sys.stdin)
print($1)" 2>/dev/null; }
uuid5() { python3 -c "import uuid;print(uuid.uuid5(uuid.NAMESPACE_URL,'marketplace-pix:$1:$2'))"; }
wait_for() { # descrição, comando, valor esperado, tentativas
  local n=${4:-30} v=""
  for _ in $(seq 1 "$n"); do v=$(eval "$2" 2>/dev/null); [ "$v" = "$3" ] && break; sleep 1; done
  check "$1" "$v" "$3"
}
post_order() { # produto, quantidade, cliente, e-mail, chave -> corpo; código HTTP em $CODE_FILE
  local out
  out=$(curl -s -w '\n%{http_code}' -X POST "$G/orders" -H 'content-type: application/json' -H "Idempotency-Key: $5" \
    -d "{\"customer_id\":\"$3\",\"customer_name\":\"Teste E2E\",\"customer_email\":\"$4\",\"items\":[{\"product_id\":\"$1\",\"quantity\":$2,\"unit_price_cents\":1}]}")
  echo "$out" | tail -n1 > "$CODE_FILE"; echo "$out" | sed '$d'
}

RUN=$RANDOM$RANDOM
CUST=$(python3 -c 'import uuid;print(uuid.uuid4())')
EMAIL="e2e.$RUN@example.com"
CORDA=$(uuid5 product corda-pular-speed); GPS=$(uuid5 product relogio-gps-trail)
TRILHA=$(uuid5 merchant trilha-sports)
stock() { curl -s "$G/inventory/stock/$1" | jget "'%s/%s' % (d['available'], d['reserved'])"; }
summary() { curl -s "$G/ledger/merchants/$TRILHA/summary?days=1"; }

echo "== 1. Saúde"
check "gateway agrega todos os serviços" "$(curl -s "$G/health" | jget "d['status']")" "ok"

echo "== 2. Catálogo"
check "busca sem acento acha Luminária" "$(curl -s "$G/catalog/products?q=luminaria" | jget "d['items'][0]['name']")" "Luminária Arco Dourado"
check "catálogo tem 24 produtos" "$(curl -s "$G/catalog/products?page_size=48" | jget "d['total']")" "24"

echo "== 3. Pedido feliz (preço vem do catálogo mesmo o cliente mandando 1 centavo)"
curl -s -X PUT "$G/inventory/stock/$CORDA" -H 'content-type: application/json' -d '{"available":25}' >/dev/null
sleep 1
S0=$(stock "$CORDA"); A0=${S0%/*}; R0=${S0#*/}
BEFORE=$(summary); B_GROSS=$(echo "$BEFORE" | jget "d['gross_sales_cents']"); B_FEES=$(echo "$BEFORE" | jget "d['platform_fees_cents']")
KEY="e2e-$RUN"
ORDER_JSON=$(post_order "$CORDA" 2 "$CUST" "$EMAIL" "$KEY"); check "POST /orders devolve 201" "$(cat "$CODE_FILE")" "201"
ORDER=$(echo "$ORDER_JSON" | jget "d['id']")
check "total = 2 x R\$ 49,90 (preço do catálogo)" "$(curl -s "$G/orders/$ORDER" | jget "d['total_cents']")" "9980"
REPLAY=$(post_order "$CORDA" 2 "$CUST" "$EMAIL" "$KEY" | jget "d['id']"); check "mesma Idempotency-Key devolve o mesmo pedido" "$REPLAY" "$ORDER"
wait_for "cobrança PIX criada" "curl -s -o /dev/null -w '%{http_code}' $G/payments/by-order/$ORDER" "200"
CH=$(curl -s "$G/payments/by-order/$ORDER" | jget "d['psp_charge_id']")
wait_for "estoque reservado (-2 livres, +2 reservados)" "stock $CORDA" "$((A0-2))/$((R0+2))"
check "webhook sem assinatura é recusado (401)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$PAYMENTS/webhooks/psp" -d "{\"event\":\"charge.paid\",\"charge_id\":\"$CH\"}")" "401"
check "pedido segue PENDING antes do pagamento" "$(curl -s "$G/orders/$ORDER" | jget "d['status']")" "PENDING"
curl -s -X POST "$G/payments/dev/psp/charges/$CH/pay" >/dev/null
wait_for "pedido vira PAID" "curl -s $G/orders/$ORDER | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "PAID"
wait_for "venda confirmada (reservas voltam, livres ficam)" "stock $CORDA" "$((A0-2))/$R0"
sleep 3
AFTER=$(summary)
check "ledger: vendas brutas +9980" "$(( $(echo "$AFTER" | jget "d['gross_sales_cents']") - B_GROSS ))" "9980"
check "ledger: taxa da plataforma +998 (10%)" "$(( $(echo "$AFTER" | jget "d['platform_fees_cents']") - B_FEES ))" "998"
check "ledger: conciliação balanceada" "$(curl -s "$G/ledger/reconciliation" | jget "d['balanced']")" "True"
wait_for "3 e-mails enviados" "curl -s '$M/search?query=to:$EMAIL' | python3 -c \"import sys,json;print(json.load(sys.stdin)['messages_count'])\"" "3" 40
check "API de notificações lista os 3 como SENT" "$(curl -s "$G/notifications?customer_id=$CUST" | jget "sorted(set(n['status'] for n in d['items']))")" "['SENT']"

echo "== 4. Sem estoque cancela pedido e cobrança"
OUT=$(post_order "$GPS" 50 "$CUST" "$EMAIL" "e2e-oos-$RUN"); ORDER2=$(echo "$OUT" | jget "d['id']"); check "pedido de 50 unidades aceito (201)" "$(cat "$CODE_FILE")" "201"
wait_for "pedido cancelado por falta de estoque" "curl -s $G/orders/$ORDER2 | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d['status'],d['cancel_reason'])\"" "CANCELLED out of stock"
wait_for "cobrança cancelada" "curl -s $G/payments/by-order/$ORDER2 | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "CANCELLED"
CH2=$(curl -s "$G/payments/by-order/$ORDER2" | jget "d['psp_charge_id']")
check "pagar PIX cancelado é recusado (409)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$G/payments/dev/psp/charges/$CH2/pay")" "409"

echo "== 5. Validações"
post_order "$(python3 -c 'import uuid;print(uuid.uuid4())')" 1 "$CUST" "$EMAIL" "e2e-unk-$RUN" >/dev/null; check "produto inexistente (422)" "$(cat "$CODE_FILE")" "422"
check "sem Idempotency-Key (400)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$G/orders" -H 'content-type: application/json' -d "{\"customer_id\":\"$CUST\",\"customer_name\":\"Teste E2E\",\"customer_email\":\"$EMAIL\",\"items\":[{\"product_id\":\"$CORDA\",\"quantity\":1}]}")" "400"

echo
if [ "$FAIL" -eq 0 ]; then printf '\033[32mTUDO OK: %d verificações\033[0m\n' "$PASS"; else printf '\033[31m%d falharam, %d passaram\033[0m\n' "$FAIL" "$PASS"; exit 1; fi
