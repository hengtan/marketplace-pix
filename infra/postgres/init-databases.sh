#!/bin/bash
# Um banco por microsserviço (isolamento de dados), no mesmo servidor Postgres para economizar recursos locais.
set -e

for db in ordering payments ledger inventory catalog notifications identity; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    SELECT 'CREATE DATABASE $db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
EOSQL
done
