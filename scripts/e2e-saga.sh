#!/usr/bin/env bash
# Cenários de falha da saga contra a stack real: pagamento que nunca chega e pagamento tardio.
# A stack precisa estar no ar com prazo curto, por exemplo:
#   SAGA_TIMEOUT_SECONDS=12 SAGA_SWEEP_INTERVAL_SECONDS=3 scripts/up.sh
# Variáveis: GATEWAY, ENV_FILE, COMPOSE (comando do docker compose da stack), SAGA_TIMEOUT_SECONDS.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/.."
ENV_FILE=${ENV_FILE:-.env}
G=${GATEWAY:-http://localhost:8000/api}
COMPOSE=${COMPOSE:-docker compose -f infra/docker-compose.yml --env-file $ENV_FILE --profile services}
TIMEOUT=${SAGA_TIMEOUT_SECONDS:-12}
SEED_PASSWORD=${IDENTITY_SEED_PASSWORD:-$(grep -E '^IDENTITY_SEED_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)}
PG_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
source "$HERE/e2e-lib.sh"

sql() { # banco, consulta
  $COMPOSE exec -T postgres psql -U "$PG_USER" -d "$1" -tA -c "$2" 2>/dev/null | tr -d '[:space:]'
}
stock() { curl -s "$G/inventory/stock/$1" -H "$(auth "$MERCHANT_TOKEN")" | jget "'%s/%s' % (d['available'], d['reserved'])"; }
order_field() { curl -s "$G/orders/$ORDER" -H "$(auth "$TOKEN")" | jget "$1"; }
payment_status() { curl -s "$G/payments/by-order/$ORDER" -H "$(auth "$TOKEN")" | jget "d['status']"; }

RUN=$RANDOM$RANDOM
EMAIL="saga.$RUN@example.com"
ITEM=$(uuid5 product kit-elasticos-forca); PRICE=6990; TRILHA=$(uuid5 merchant trilha-sports)
REG=$(curl -s -X POST "$G/auth/register" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"name\":\"Saga E2E\",\"password\":\"Saga-senha-$RUN-segura\"}")
TOKEN=$(echo "$REG" | jget "d['access_token']"); CUST=$(echo "$REG" | jget "d['user']['id']")
MERCHANT_TOKEN=$(login "trilha-sports@marketplace-pix.local" "$SEED_PASSWORD")
ADMIN_TOKEN=$(login "admin@marketplace-pix.local" "$SEED_PASSWORD")
gross() { curl -s "$G/ledger/merchants/$TRILHA/summary?days=1" -H "$(auth "$MERCHANT_TOKEN")" | jget "d['gross_sales_cents']"; }
curl -s -X PUT "$G/inventory/stock/$ITEM" -H 'content-type: application/json' -H "$(auth "$MERCHANT_TOKEN")" -d '{"available":25}' >/dev/null
sleep 1
S0=$(stock "$ITEM"); A0=${S0%/*}; R0=${S0#*/}

echo "== Cenário A: o pagamento nunca chega (prazo da saga: ${TIMEOUT}s)"
ORDER=$(post_order "$ITEM" 2 "$CUST" "$EMAIL" "saga-a-$RUN" "$TOKEN" | jget "d['id']"); check "pedido criado (201)" "$(cat "$CODE_FILE")" "201"
wait_for "cobrança PIX pendente" "payment_status" "PENDING"
wait_for "estoque reservado" "stock $ITEM" "$((A0-2))/$((R0+2))"
wait_for "o prazo estoura e o pedido é cancelado por saga timeout" "order_field \"d['status'] + ' ' + d['cancel_reason']\"" "CANCELLED saga timeout" $((TIMEOUT + 45))
wait_for "compensação: cobrança cancelada" "payment_status" "CANCELLED"
wait_for "compensação: estoque liberado" "stock $ITEM" "$A0/$R0"
check "auditoria registrou o timeout uma vez" "$(sql ordering "select count(*) from order_audit where order_id='$ORDER' and kind='SAGA_TIMEOUT'")" "1"
check "um único OrderCancelled no outbox" "$(sql ordering "select count(*) from outbox_events where aggregate_id='$ORDER' and type='OrderCancelled'")" "1"
CH=$(curl -s "$G/payments/by-order/$ORDER" -H "$(auth "$TOKEN")" | jget "d['psp_charge_id']")
check "pagar o PIX cancelado é recusado (409)" "$(status -X POST "$G/payments/dev/psp/charges/$CH/pay" -H "$(auth "$TOKEN")")" "409"

echo "== Cenário B: o pagamento chega depois do cancelamento"
G0=$(gross)
$COMPOSE stop ordering-worker >/dev/null 2>&1
check "worker do ordering parado (simula o atraso na saga)" "$($COMPOSE ps --status running --services 2>/dev/null | grep -c '^ordering-worker$')" "0"
ORDER=$(post_order "$ITEM" 1 "$CUST" "$EMAIL" "saga-b-$RUN" "$TOKEN" | jget "d['id']"); check "pedido criado (201)" "$(cat "$CODE_FILE")" "201"
wait_for "cobrança PIX pendente" "payment_status" "PENDING" 10
wait_for "estoque reservado" "stock $ITEM" "$((A0-1))/$((R0+1))" 10
CH=$(curl -s "$G/payments/by-order/$ORDER" -H "$(auth "$TOKEN")" | jget "d['psp_charge_id']")
curl -s -X POST "$G/payments/dev/psp/charges/$CH/pay" -H "$(auth "$TOKEN")" >/dev/null
wait_for "o PSP confirma e o payments marca CONFIRMED" "payment_status" "CONFIRMED"
wait_for "ledger lançou a venda" "echo \$(( \$(gross) - G0 ))" "$PRICE"
wait_for "estoque confirmado (reserva virou venda)" "stock $ITEM" "$((A0-1))/$R0"
check "o pedido ainda está PENDING (ninguém consumiu o pagamento)" "$(order_field "d['status']")" "PENDING"
sleep $((TIMEOUT + 2))
$COMPOSE run --rm --no-deps -T ordering-api python -m ordering.saga_main --once >/dev/null 2>&1
check "o timeout cancela o pedido antes do pagamento ser processado" "$(order_field "d['status'] + ' ' + d['cancel_reason']")" "CANCELLED saga timeout"
$COMPOSE start ordering-worker >/dev/null 2>&1
wait_for "pagamento tardio reembolsado (REFUNDED)" "payment_status" "REFUNDED" 90
check "o pedido continua CANCELLED" "$(order_field "d['status']")" "CANCELLED"
check "auditoria do pagamento tardio registrada uma vez" "$(sql ordering "select count(*) from order_audit where order_id='$ORDER' and kind='LATE_PAYMENT'")" "1"
check "um único pedido de reembolso no outbox" "$(sql ordering "select count(*) from outbox_events where aggregate_id='$ORDER' and type='PaymentRefundRequested'")" "1"
check "PSP marcou a cobrança como reembolsada" "$(sql payments "select status from simulated_psp_charges where id='$CH'")" "REFUNDED"
wait_for "ledger estornou a venda (receita volta ao patamar anterior)" "echo \$(( \$(gross) - G0 ))" "0"
check "ledger tem a transação de estorno" "$(sql ledger "select count(*) from ledger_transactions where order_id='$ORDER' and kind='REVERSAL'")" "1"
check "ledger segue balanceado" "$(curl -s "$G/ledger/reconciliation" -H "$(auth "$ADMIN_TOKEN")" | jget "d['balanced'] and d['accounts_consistent']")" "True"
wait_for "estoque devolvido à prateleira" "stock $ITEM" "$A0/$R0"

summary_result
