"""建立显式 Prediction run 状态机与来源分桶。

Revision ID: 20260715_0002
Revises: 20260715_0001
Create Date: 2026-07-15
"""
from __future__ import annotations

from alembic import op


revision = "20260715_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def _execute(sql: str) -> None:
    op.execute(sql)


def upgrade() -> None:
    _execute(
        "ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS "
        "source_type TEXT NOT NULL DEFAULT 'ai'"
    )
    _execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname='ck_agent_predictions_source_type'
            ) THEN
                ALTER TABLE agent_predictions ADD CONSTRAINT ck_agent_predictions_source_type
                CHECK (source_type IN ('ai','manual'));
            END IF;
        END $$
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_runs (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            anchor_time TEXT NULL,
            anchor_price DOUBLE PRECISION NULL,
            market_provider TEXT NULL,
            market_as_of TIMESTAMPTZ NULL,
            llm_provider TEXT NULL,
            llm_model TEXT NULL,
            prediction_id UUID NULL,
            failure_code TEXT NULL,
            failure_detail TEXT NULL,
            provider_attempts INTEGER NOT NULL DEFAULT 0,
            prompt_tokens BIGINT NOT NULL DEFAULT 0,
            completion_tokens BIGINT NOT NULL DEFAULT 0,
            total_tokens BIGINT NOT NULL DEFAULT 0,
            latency_ms BIGINT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_prediction_runs_status CHECK (
                status IN ('queued','running','succeeded','unavailable','failed','cancelled')
            ),
            CONSTRAINT ck_prediction_runs_attempts CHECK (provider_attempts >= 0 AND provider_attempts <= 2),
            CONSTRAINT fk_prediction_runs_prediction FOREIGN KEY(prediction_id,user_id)
                REFERENCES agent_predictions(id,user_id)
        )
        """
    )
    _execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_runs_active "
        "ON prediction_runs(user_id,symbol,timeframe,prompt_version) "
        "WHERE status IN ('queued','running')"
    )
    _execute(
        "CREATE INDEX IF NOT EXISTS idx_prediction_runs_owner_created "
        "ON prediction_runs(user_id,created_at DESC)"
    )
    _execute(
        "CREATE INDEX IF NOT EXISTS idx_prediction_runs_recovery "
        "ON prediction_runs(status,updated_at) "
        "WHERE status IN ('queued','running')"
    )


def downgrade() -> None:
    _execute("DROP TABLE IF EXISTS prediction_runs")
    _execute(
        "ALTER TABLE agent_predictions DROP CONSTRAINT IF EXISTS "
        "ck_agent_predictions_source_type"
    )
    _execute("ALTER TABLE agent_predictions DROP COLUMN IF EXISTS source_type")
