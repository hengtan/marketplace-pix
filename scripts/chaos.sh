#!/usr/bin/env bash
# Teste de caos: derruba catalog, payments e redis (docker compose stop), um de cada vez, e valida
# pelo gateway que o disjuntor abre, as respostas são rápidas (fail fast), o sistema volta sozinho
# e que os pedidos em andamento não se perdem (a saga continua pelo outbox quando o serviço volta).
#
# Uso:   scripts/chaos.sh
# Env:   CHAOS_PROJECT   projeto do docker compose (padrão: o da stack do scripts/up.sh)
#        CHAOS_COMPOSE_FILES  arquivos extras de compose, separados por espaço
#        GATEWAY         URL do gateway (padrão http://localhost:8000)
#        FAST_MS         limite de "resposta rápida" em ms (padrão 500)
#        RECOVERY_TIMEOUT segundos esperando a recuperação (padrão 90)
# Sai com código diferente de zero se alguma checagem falhar. Sempre religa o que derrubou.
set -uo pipefail
cd "$(dirname "$0")/.."

PROJECT=${CHAOS_PROJECT:-marketplace-pix}
GATEWAY=${GATEWAY:-http://localhost:8000}
G="$GATEWAY/api"
FAST_MS=${FAST_MS:-500}
RECOVERY_TIMEOUT=${RECOVERY_TIMEOUT:-90}

FILES=(-f infra/docker-compose.yml)
for extra in ${CHAOS_COMPOSE_FILES:-}; do FILES+=(-f "$extra"); done
COMPOSE=(docker compose -p "$PROJECT" "${FILES[@]}" --env-file .env --profile services)

PASS=0; FAIL=0; REPORT=()
STOPPED=()
RUN=$RANDOM$RANDOM

ok()   { PASS=$((PASS+1)); REPORT+=("OK     $1"); printf '  \033[32mOK\033[0m     %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); REPORT+=("FALHA  $1 (obtido: $2)"); printf '  \033[31mFALHA\033[0m  %s (obtido: %s)\n' "$1" "$2"; }
info() { printf '  ..     %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$2 | esperado: $3"; fi; }
section() { printf '\n== %s\n' "$1"; REPORT+=("" "== $1"); }

jget() { python3 -c "import sys,json
d=json.load(sys.stdin)
print($1)" 2>/dev/null; }
uuid5() { python3 -c "import uuid;print(uuid.uuid5(uuid.NAMESPACE_URL,'marketplace-pix:$1:$2'))"; }

probe() { # url [método] -> "status milissegundos"
  curl -s -o /dev/null -m 15 -X "${2:-GET}" -w '%{http_code} %{time_total}' "$1" 2>/dev/null \
    | awk '{printf "%s %d", $1, $2*1000}'
}
status_of() { probe "$1" "${2:-GET}" | cut -d' ' -f1; }
ms_of() { probe "$1" "${2:-GET}" | cut -d' ' -f2; }

forget() {
  local keep=() s r skip
  for s in ${STOPPED[@]+"${STOPPED[@]}"}; do
    skip=0; for r in "$@"; do [ "$s" = "$r" ] && skip=1; done
    [ "$skip" = 0 ] && keep+=("$s")
  done
  STOPPED=(${keep[@]+"${keep[@]}"})
}
stop_service()  { "${COMPOSE[@]}" stop -t 3 "$@" >/dev/null 2>&1; STOPPED+=("$@"); }
start_service() { "${COMPOSE[@]}" start "$@" >/dev/null 2>&1; forget "$@"; }
restore() {
  if [ ${#STOPPED[@]} -gt 0 ]; then
    echo; echo "religando: ${STOPPED[*]}"
    "${COMPOSE[@]}" start ${STOPPED[@]+"${STOPPED[@]}"} >/dev/null 2>&1
  fi
}

breaker_state() { curl -s -m 5 "$G/health" | jget "d['breakers']['$1']['state']"; }
counter() { # nome da métrica com labels, ex.: 'resilience_rate_limit_backend_total{backend="redis"}'
  curl -s -m 5 "$GATEWAY/metrics" | grep -F "$1" | head -1 | awk '{print int($2)}'
}
wait_until() { # descrição, comando, valor esperado, segundos
  local limit=${4:-30} start=$SECONDS v=""
  while [ $((SECONDS-start)) -lt "$limit" ]; do
    v=$(eval "$2" 2>/dev/null); [ "$v" = "$3" ] && { RECOVERY_SECS=$((SECONDS-start)); return 0; }
    sleep 1
  done
  RECOVERY_SECS=$limit; return 1
}
post_order() { # produto cliente e-mail chave -> corpo; código em $CODE_FILE
  local out
  out=$(curl -s -m 15 -w '\n%{http_code}' -X POST "$G/orders" -H 'content-type: application/json' \
    -H "Idempotency-Key: $4" \
    -d "{\"customer_id\":\"$2\",\"customer_name\":\"Caos\",\"customer_email\":\"$3\",\"items\":[{\"product_id\":\"$1\",\"quantity\":1,\"unit_price_cents\":1}]}")
  echo "$out" | tail -n1 > "$CODE_FILE"; echo "$out" | sed '$d'
}
CODE_FILE=$(mktemp); trap 'rm -f "$CODE_FILE"; restore' EXIT

PRODUCT=$(uuid5 product corda-pular-speed)
CUSTOMER=$(python3 -c 'import uuid;print(uuid.uuid4())')

section "0. Linha de base"
curl -s -m 10 -o /dev/null -X PUT "$G/inventory/stock/$PRODUCT" -H 'content-type: application/json' -d '{"available": 1000}'
info "estoque do produto de teste reposto (evita falso negativo por falta de estoque)"
check "gateway responde" "$(status_of "$G/catalog/products")" "200"
for s in catalog ordering payments; do
  check "breaker de $s começa fechado" "$(breaker_state $s)" "closed"
done
BASE_MS=$(ms_of "$G/catalog/products")
info "latência base do catálogo: ${BASE_MS} ms"

section "1. Catálogo fora do ar"
stop_service catalog-api
sleep 2
FIRST=$(probe "$G/catalog/products")
info "primeira chamada com o catálogo morto: $FIRST (status ms)"
for _ in $(seq 1 25); do probe "$G/catalog/products" >/dev/null; done
check "breaker do catálogo abriu" "$(breaker_state catalog)" "open"
SAMPLE=$(probe "$G/catalog/products")
check "com o circuito aberto o gateway responde 503" "$(echo "$SAMPLE" | cut -d' ' -f1)" "503"
SAMPLE_MS=$(echo "$SAMPLE" | cut -d' ' -f2)
if [ "$SAMPLE_MS" -le "$FAST_MS" ]; then ok "fail fast: 503 em ${SAMPLE_MS} ms (limite ${FAST_MS} ms)"; else bad "fail fast" "${SAMPLE_MS} ms"; fi
BODY=$(curl -s -m 5 -D - "$G/catalog/products")
check "503 estruturado (code)" "$(echo "$BODY" | tail -1 | jget "d['code']")" "circuit_open"
check "503 estruturado (service)" "$(echo "$BODY" | tail -1 | jget "d['service']")" "catalog"
if echo "$BODY" | grep -qi '^retry-after: [0-9]'; then ok "cabeçalho Retry-After presente"; else bad "Retry-After" "ausente"; fi
check "inventory continua respondendo (isolamento)" "$(status_of "$G/inventory/stock/$PRODUCT")" "200"
check "agregado /api/health mostra o breaker aberto" "$(curl -s -m 5 "$G/health" | jget "d['breakers']['catalog']['state']")" "open"
ORD=$(post_order "$PRODUCT" "$CUSTOMER" "caos.$RUN@example.com" "chaos-cat-$RUN"); CODE=$(cat "$CODE_FILE")
if [ "$CODE" = "503" ] || [ "$CODE" = "502" ] || [ "$CODE" = "504" ]; then ok "criar pedido sem catálogo degrada com $CODE (não cria pedido torto)"; else bad "POST /orders sem catálogo" "$CODE $ORD"; fi

start_service catalog-api
if wait_until "recuperação do catálogo" "status_of $G/catalog/products" "200" "$RECOVERY_TIMEOUT"; then
  ok "catálogo voltou sozinho em ${RECOVERY_SECS}s (sem reiniciar o gateway)"
else bad "recuperação do catálogo" "não voltou em ${RECOVERY_TIMEOUT}s"; fi
close_breaker() { probe "$G/$2" >/dev/null; breaker_state "$1"; }
if wait_until "breaker catalog" "close_breaker catalog catalog/products" "closed" 30; then ok "breaker do catálogo fechou de novo após as sondas do half-open"; else bad "breaker do catálogo" "$(breaker_state catalog)"; fi

section "2. Payments fora do ar (a saga não perde pedidos)"
ORD_BEFORE=$(post_order "$PRODUCT" "$CUSTOMER" "caos.a.$RUN@example.com" "chaos-pay-a-$RUN")
ID_A=$(echo "$ORD_BEFORE" | jget "d['id']")
check "pedido A criado antes da queda" "$(cat "$CODE_FILE")" "201"
stop_service payments-api payments-worker
sleep 2
ORD_DURING=$(post_order "$PRODUCT" "$CUSTOMER" "caos.b.$RUN@example.com" "chaos-pay-b-$RUN")
ID_B=$(echo "$ORD_DURING" | jget "d['id']")
check "pedido B criado com payments fora (ordering não depende dele)" "$(cat "$CODE_FILE")" "201"
for _ in $(seq 1 25); do probe "$G/payments/by-order/$ID_B" >/dev/null; done
check "breaker de payments abriu" "$(breaker_state payments)" "open"
SAMPLE=$(probe "$G/payments/by-order/$ID_B")
check "consulta de pagamento responde 503 com o circuito aberto" "$(echo "$SAMPLE" | cut -d' ' -f1)" "503"
SAMPLE_MS=$(echo "$SAMPLE" | cut -d' ' -f2)
if [ "$SAMPLE_MS" -le "$FAST_MS" ]; then ok "fail fast: ${SAMPLE_MS} ms"; else bad "fail fast payments" "${SAMPLE_MS} ms"; fi
check "ordering segue lendo pedidos" "$(status_of "$G/orders/$ID_B")" "200"
check "pedido B está PENDING" "$(curl -s -m 5 "$G/orders/$ID_B" | jget "d['status']")" "PENDING"

start_service payments-api payments-worker
if wait_until "payments" "status_of $G/payments/by-order/$ID_B" "200" "$RECOVERY_TIMEOUT"; then
  ok "cobrança do pedido B foi criada depois que o payments voltou, em ${RECOVERY_SECS}s (saga retomou via Kafka)"
else bad "cobrança do pedido B" "não apareceu em ${RECOVERY_TIMEOUT}s"; fi
wait_until "payments A" "status_of $G/payments/by-order/$ID_A" "200" 30 \
  && ok "cobrança do pedido A existe" || bad "cobrança do pedido A" "ausente"
if wait_until "breaker payments" "close_breaker payments payments/by-order/$ID_B" "closed" 30; then ok "breaker de payments fechou de novo após as sondas do half-open"; else bad "breaker de payments" "$(breaker_state payments)"; fi
login() {
  curl -s -X POST "$G/auth/login" -H 'content-type: application/json' -d "{\"email\":\"$1\",\"password\":\"$2\"}" | jget "d['access_token']"
}
auth() { echo "Authorization: Bearer $1"; }
ENV_FILE=${ENV_FILE:-.env}
SEED_PASSWORD=${IDENTITY_SEED_PASSWORD:-$(grep -E '^IDENTITY_SEED_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)}
PAY_TOKEN=$(login "trilha-sports@marketplace-pix.local" "$SEED_PASSWORD")
for ID in "$ID_A" "$ID_B"; do
  CHARGE=$(curl -s -m 5 "$G/payments/by-order/$ID" | jget "d['psp_charge_id']")
  curl -s -m 10 -X POST "$G/payments/dev/psp/charges/$CHARGE/pay" -H "$(auth "$PAY_TOKEN")" >/dev/null
done
wait_until "A paga" "curl -s $G/orders/$ID_A | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "PAID" 60 \
  && ok "pedido A chegou a PAID" || bad "pedido A" "não ficou PAID"
wait_until "B paga" "curl -s $G/orders/$ID_B | python3 -c \"import sys,json;print(json.load(sys.stdin)['status'])\"" "PAID" 60 \
  && ok "pedido B (criado durante a queda) chegou a PAID" || bad "pedido B" "não ficou PAID"

section "3. Redis fora do ar (rate limit degrada, tráfego segue)"
FALLBACK_BEFORE=$(counter 'resilience_rate_limit_backend_total{backend="memory_fallback"}'); FALLBACK_BEFORE=${FALLBACK_BEFORE:-0}
stop_service redis
sleep 2
CODES=""; TIMES=""
for _ in $(seq 1 30); do
  R=$(probe "$G/catalog/products"); CODES="$CODES $(echo "$R" | cut -d' ' -f1)"
  TIMES="$TIMES $(echo "$R" | cut -d' ' -f2)"
done
NOT200=$(echo "$CODES" | tr ' ' '\n' | grep -v '^200$' | grep -vc '^$')
check "30 requisições sem Redis, todas 200" "$NOT200" "0"
SORTED=$(echo "$TIMES" | tr ' ' '\n' | grep -v '^$' | sort -n)
P50=$(echo "$SORTED" | sed -n 15p); P90=$(echo "$SORTED" | sed -n 27p); MAXMS=$(echo "$SORTED" | tail -1)
info "latência sem Redis: p50=${P50} ms, p90=${P90} ms, max=${MAXMS} ms"
if [ "$P50" -le "$FAST_MS" ] && [ "$P90" -le 1000 ]; then ok "sem Redis o gateway segue rápido (o breaker do Redis evita esperar timeout em toda chamada)"; else bad "latência sem Redis" "p50=${P50} p90=${P90}"; fi
FALLBACK_AFTER=$(counter 'resilience_rate_limit_backend_total{backend="memory_fallback"}'); FALLBACK_AFTER=${FALLBACK_AFTER:-0}
if [ "$FALLBACK_AFTER" -gt "$FALLBACK_BEFORE" ]; then ok "métrica de fallback em memória subiu ($FALLBACK_BEFORE -> $FALLBACK_AFTER)"; else bad "métrica memory_fallback" "$FALLBACK_BEFORE -> $FALLBACK_AFTER"; fi
HDR=$(curl -s -m 5 -D - -o /dev/null "$G/catalog/products")
if echo "$HDR" | grep -qi '^ratelimit-limit:'; then ok "headers RateLimit-* continuam saindo (limiter em memória)"; else bad "RateLimit-Limit" "ausente"; fi

REDIS_BEFORE=$(counter 'resilience_rate_limit_backend_total{backend="redis"}'); REDIS_BEFORE=${REDIS_BEFORE:-0}
start_service redis
RECOVERED=1
for _ in $(seq 1 "$RECOVERY_TIMEOUT"); do
  probe "$G/catalog/products" >/dev/null
  NOW=$(counter 'resilience_rate_limit_backend_total{backend="redis"}'); NOW=${NOW:-0}
  [ "$NOW" -gt "$REDIS_BEFORE" ] && { RECOVERED=0; break; }
  sleep 1
done
if [ "$RECOVERED" = 0 ]; then ok "gateway voltou a usar o Redis sozinho"; else bad "retorno ao Redis" "contador redis não subiu"; fi

section "4. Pós-caos"
for s in catalog ordering payments inventory ledger; do
  check "serviço $s saudável no agregado" "$(curl -s -m 5 "$G/health" | jget "d['services']['$s']")" "ok"
done
for s in catalog ordering payments; do check "breaker de $s fechado" "$(breaker_state $s)" "closed"; done

echo
echo "================ RELATÓRIO DO TESTE DE CAOS ================"
printf '%s\n' "${REPORT[@]}"
echo "------------------------------------------------------------"
echo "passaram: $PASS   falharam: $FAIL"
[ "$FAIL" -eq 0 ]
