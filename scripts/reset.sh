#!/usr/bin/env bash
# Apaga containers e VOLUMES (bancos e Kafka). Use quando quiser recomeçar do zero.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" != "--yes" ]; then
  read -r -p "Isso apaga todos os dados locais (bancos, Kafka). Continuar? [s/N] " answer
  [ "$answer" = "s" ] || { echo "cancelado"; exit 0; }
fi
docker compose -f infra/docker-compose.yml --env-file .env --profile services down -v --remove-orphans
echo "pronto. Suba de novo com scripts/up.sh"
