#!/usr/bin/env bash
# Sobe a infraestrutura e todos os serviços (build incluso) e espera ficarem saudáveis.
# Uso: scripts/up.sh [--obs]   (--obs liga também Prometheus, Grafana e Jaeger)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 12)/" .env
  sed -i.bak "s/^PSP_WEBHOOK_SECRET=.*/PSP_WEBHOOK_SECRET=$(openssl rand -hex 24)/" .env
  sed -i.bak "s/^INTERNAL_AUTH_SECRET=.*/INTERNAL_AUTH_SECRET=$(openssl rand -hex 32)/" .env
  sed -i.bak "s/^IDENTITY_SEED_PASSWORD=.*/IDENTITY_SEED_PASSWORD=praca1234/" .env
  rm -f .env.bak
  echo ".env criado com segredos novos"
fi
if ! grep -q "^INTERNAL_AUTH_SECRET=" .env; then
  echo "INTERNAL_AUTH_SECRET=$(openssl rand -hex 24)" >> .env
  echo "INTERNAL_AUTH_SECRET gerado e adicionado ao .env"
fi
if ! grep -q "^IDENTITY_SEED_PASSWORD=" .env; then
  echo "IDENTITY_SEED_PASSWORD=praca1234" >> .env
  echo "IDENTITY_SEED_PASSWORD (apenas desenvolvimento) adicionado ao .env"
fi

FILES=(-f infra/docker-compose.yml)
if [ "${1:-}" = "--obs" ]; then
  FILES+=(-f infra/docker-compose.observability.yml)
  echo "observabilidade ligada (Prometheus, Grafana, Jaeger)"
fi
COMPOSE=(docker compose "${FILES[@]}" --env-file .env --profile services)
"${COMPOSE[@]}" up -d --wait postgres
for db in ordering payments ledger inventory catalog notifications identity; do
  "${COMPOSE[@]}" exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\" | grep -q 1 || psql -U \"\$POSTGRES_USER\" -d postgres -c 'CREATE DATABASE $db'" >/dev/null
done
"${COMPOSE[@]}" up -d --build

echo "aguardando o gateway reportar todos os serviços saudáveis..."
for _ in $(seq 1 90); do
  if curl -fs http://localhost:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -s http://localhost:8000/api/health || true
echo
cat <<URLS

Loja (frontend)     http://localhost:5173
API (gateway)       http://localhost:8000/docs
Kafka UI            http://localhost:8081
E-mails (Mailpit)   http://localhost:8025
Teste completo      scripts/e2e.sh
Grafana / Jaeger    http://localhost:3000 (admin/admin) e http://localhost:16686  (com --obs)
URLS
