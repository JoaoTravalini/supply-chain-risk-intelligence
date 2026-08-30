"""PostgreSQL checkpoint persistence for LangGraph investigations."""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Self

from langgraph.checkpoint.postgres import PostgresSaver

from supplychain.agent.errors import AgentConfigurationError, AgentPersistenceError

AGENT_POSTGRES_DSN_ENV = "SUPPLYCHAIN_AGENT_POSTGRES_DSN"


class PostgresCheckpointStore(AbstractContextManager["PostgresCheckpointStore"]):
    """Own the official LangGraph PostgreSQL saver context."""

    def __init__(self, dsn: str) -> None:
        self._dsn = _validate_dsn(dsn)
        self._context: AbstractContextManager[PostgresSaver] | None = None
        self._checkpointer: PostgresSaver | None = None

    @property
    def checkpointer(self) -> PostgresSaver:
        """Return the active official LangGraph checkpointer."""

        if self._checkpointer is None:
            raise AgentPersistenceError("PostgreSQL checkpointer is not open")
        return self._checkpointer

    def __enter__(self) -> Self:
        self._context = PostgresSaver.from_conn_string(self._dsn)
        try:
            self._checkpointer = self._context.__enter__()
        except Exception as exc:
            raise AgentPersistenceError("Unable to open PostgreSQL checkpointer") from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._context is not None:
            return self._context.__exit__(exc_type, exc, traceback)
        return None


def checkpoint_store_from_env() -> PostgresCheckpointStore:
    """Create a PostgreSQL checkpoint store from the configured environment."""

    dsn = os.environ.get(AGENT_POSTGRES_DSN_ENV)
    if dsn is None or not dsn.strip():
        raise AgentConfigurationError(f"{AGENT_POSTGRES_DSN_ENV} must be set")
    return PostgresCheckpointStore(dsn)


def setup_postgres_checkpoints_from_env() -> None:
    """Run explicit one-time LangGraph checkpoint schema setup."""

    with checkpoint_store_from_env() as store:
        try:
            store.checkpointer.setup()
        except Exception as exc:
            raise AgentPersistenceError("Unable to set up PostgreSQL checkpoints") from exc


def _validate_dsn(dsn: str) -> str:
    if not dsn.strip():
        raise AgentConfigurationError("PostgreSQL DSN must not be blank")
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise AgentConfigurationError("PostgreSQL DSN must use a PostgreSQL URI scheme")
    return dsn


def main() -> None:
    """Command entrypoint for explicit checkpoint setup."""

    setup_postgres_checkpoints_from_env()
    print("LangGraph PostgreSQL checkpoint schema is ready.")


if __name__ == "__main__":
    main()
