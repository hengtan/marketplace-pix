#!/usr/bin/env bash
# Funções compartilhadas pelos scripts de ponta a ponta (use com `source`).
# Espera G (URL do gateway) definido e um diretório de trabalho na raiz do repositório.
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
login() { # e-mail, senha -> access token
  curl -s -X POST "$G/auth/login" -H 'content-type: application/json' -d "{\"email\":\"$1\",\"password\":\"$2\"}" | jget "d['access_token']"
}
auth() { echo "Authorization: Bearer $1"; }
post_order() { # produto, quantidade, cliente, e-mail, chave, [token] -> corpo; código HTTP em $CODE_FILE
  local out token=${6:-}
  out=$(curl -s -w '\n%{http_code}' -X POST "$G/orders" -H 'content-type: application/json' -H "Idempotency-Key: $5" \
    ${token:+-H "$(auth "$token")"} \
    -d "{\"customer_id\":\"$3\",\"customer_name\":\"Teste E2E\",\"customer_email\":\"$4\",\"items\":[{\"product_id\":\"$1\",\"quantity\":$2,\"unit_price_cents\":1}]}")
  echo "$out" | tail -n1 > "$CODE_FILE"; echo "$out" | sed '$d'
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
summary_result() {
  echo
  if [ "$FAIL" -eq 0 ]; then printf '\033[32mTUDO OK: %d verificações\033[0m\n' "$PASS"; else printf '\033[31m%d falharam, %d passaram\033[0m\n' "$FAIL" "$PASS"; exit 1; fi
}
