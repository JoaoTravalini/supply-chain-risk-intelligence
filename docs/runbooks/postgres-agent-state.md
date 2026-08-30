# Local PostgreSQL Agent State Runbook

This runbook starts the local PostgreSQL database used by Stage 13 LangGraph
checkpoint persistence.

All values below are synthetic local-development examples. Do not commit real
passwords, personal DSNs, cloud credentials, or production endpoints.

## Configure PowerShell Environment

```powershell
$env:SUPPLYCHAIN_AGENT_POSTGRES_DB = "supplychain_agent"
$env:SUPPLYCHAIN_AGENT_POSTGRES_USER = "supplychain_agent"
$env:SUPPLYCHAIN_AGENT_POSTGRES_PASSWORD = "<local-development-password>"
$env:SUPPLYCHAIN_AGENT_POSTGRES_PORT = "5432"
$env:SUPPLYCHAIN_AGENT_POSTGRES_DSN = "postgresql://$env:SUPPLYCHAIN_AGENT_POSTGRES_USER:$env:SUPPLYCHAIN_AGENT_POSTGRES_PASSWORD@localhost:$env:SUPPLYCHAIN_AGENT_POSTGRES_PORT/$env:SUPPLYCHAIN_AGENT_POSTGRES_DB"
```

## Start PostgreSQL

```powershell
docker compose up -d agent-postgres
```

## Check Health

```powershell
docker compose ps agent-postgres
```

Wait until the service reports healthy.

## Initialize LangGraph Checkpoints

Run the explicit one-time setup operation for the local database:

```powershell
uv run python -m supplychain.agent.persistence
```

## Run Persistence Smoke

```powershell
uv run python -m supplychain.agent.service
```

The smoke creates one synthetic investigation, closes resources, opens a new
service/checkpointer instance, retrieves the same thread state, creates a second
thread, and verifies isolation. It does not print the DSN or password.

## Stop PostgreSQL

Stop the container while preserving the named local Docker volume:

```powershell
docker compose stop agent-postgres
```

## Optional Destructive Cleanup

This deletes the local PostgreSQL container and named volume. Use only when you
intend to destroy local checkpoint data.

```powershell
docker compose down -v
```
