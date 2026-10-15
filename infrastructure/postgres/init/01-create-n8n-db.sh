#!/bin/sh
# Runs only when the PostgreSQL data volume is initialized for the first time.
set -eu

psql -X -q -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v app_database="$POSTGRES_DB" \
  -v n8n_database="$N8N_DB_NAME" \
  -v n8n_user="$N8N_DB_USER" \
  -v n8n_password="$N8N_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'n8n_user', :'n8n_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'n8n_user')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'n8n_database', :'n8n_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'n8n_database')
\gexec

-- Keep each logical database accessible only to its owner/bootstrap role.
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'app_database')
\gexec
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'n8n_database')
\gexec
SQL
