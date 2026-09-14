"""建立核心 PostgreSQL schema 并兼容既有 Prediction 表。

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15
"""
from __future__ import annotations

from alembic import op


revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None


def _execute(sql: str) -> None:
    op.execute(sql)


def upgrade() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_import_batches (
            id UUID PRIMARY KEY,
            source_digest TEXT NOT NULL,
            status TEXT NOT NULL,
            row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ NULL
        )
        """
    )
    _execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_legacy_import_batches_source_digest "
        "ON legacy_import_batches(source_digest)"
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS agent_predictions (
            id UUID NOT NULL,
            user_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            agent TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            thesis TEXT NOT NULL,
            anchor_timeframe TEXT NOT NULL,
            anchor_time TEXT NOT NULL,
            anchor_price DOUBLE PRECISION NOT NULL,
            entry_type TEXT NULL,
            entry DOUBLE PRECISION NULL,
            stop DOUBLE PRECISION NULL,
            target1 DOUBLE PRECISION NULL,
            target2 DOUBLE PRECISION NULL,
            invalidation_price DOUBLE PRECISION NULL,
            range_low DOUBLE PRECISION NULL,
            range_high DOUBLE PRECISION NULL,
            scenarios JSONB NOT NULL,
            report_id TEXT NULL,
            status TEXT NOT NULL,
            prompt_version TEXT NOT NULL DEFAULT 'legacy',
            evidence_provider TEXT NULL,
            evidence_as_of TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (id, user_id)
        )
        """
    )
    _execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='agent_predictions'
                  AND column_name='id' AND data_type='text'
            ) THEN
                IF EXISTS (SELECT 1 FROM agent_predictions WHERE id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') THEN
                    RAISE EXCEPTION 'agent_predictions contains non-UUID ids';
                END IF;
                ALTER TABLE agent_predictions ALTER COLUMN id TYPE UUID USING id::uuid;
            END IF;
        END $$
        """
    )
    _execute("ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS scenarios JSONB")
    _execute(
        """
        UPDATE agent_predictions SET scenarios = jsonb_build_array(
            jsonb_build_object('name','历史记录：原始情景未归档','probability',50,'invalidation','需重新评估'),
            jsonb_build_object('name','历史记录：需重新评估','probability',50,'invalidation','生成新预测后替代')
        ) WHERE scenarios IS NULL
        """
    )
    _execute("ALTER TABLE agent_predictions ALTER COLUMN scenarios SET NOT NULL")
    _execute("ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS report_id TEXT NULL")
    _execute("ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS prompt_version TEXT NOT NULL DEFAULT 'legacy'")
    _execute("ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS evidence_provider TEXT NULL")
    _execute("ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS evidence_as_of TIMESTAMPTZ NULL")
    _execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_predictions_id_user_id_key') THEN
                ALTER TABLE agent_predictions ADD CONSTRAINT agent_predictions_id_user_id_key UNIQUE(id,user_id);
            END IF;
        END $$
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_agent_predictions_user_created ON agent_predictions(user_id,created_at DESC)")
    _execute("CREATE INDEX IF NOT EXISTS idx_agent_predictions_owner_ticker ON agent_predictions(user_id,symbol,created_at DESC)")
    _execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_predictions_idempotency "
        "ON agent_predictions(user_id,symbol,anchor_timeframe,anchor_time,prompt_version)"
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS agent_prediction_outcomes (
            prediction_id UUID NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            resolved_at TIMESTAMPTZ NULL,
            entry_time TIMESTAMPTZ NULL,
            entry_price DOUBLE PRECISION NULL,
            pct_since_anchor DOUBLE PRECISION NULL,
            resolution_reason TEXT NULL,
            evaluated_through TIMESTAMPTZ NULL,
            market_provider TEXT NULL,
            market_as_of TIMESTAMPTZ NULL,
            algorithm_version TEXT NOT NULL DEFAULT 'legacy',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(prediction_id,user_id),
            FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id)
        )
        """
    )
    _execute("ALTER TABLE agent_prediction_outcomes ADD COLUMN IF NOT EXISTS market_provider TEXT NULL")
    _execute("ALTER TABLE agent_prediction_outcomes ADD COLUMN IF NOT EXISTS market_as_of TIMESTAMPTZ NULL")
    _execute("ALTER TABLE agent_prediction_outcomes ADD COLUMN IF NOT EXISTS algorithm_version TEXT NOT NULL DEFAULT 'legacy'")
    _execute("CREATE INDEX IF NOT EXISTS idx_agent_prediction_outcomes_owner_status ON agent_prediction_outcomes(user_id,status,updated_at DESC)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS agent_run_archive (
            id BIGSERIAL PRIMARY KEY,
            run_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            layer TEXT NOT NULL,
            prediction_id UUID NULL,
            model TEXT NOT NULL,
            prompt_tokens BIGINT NOT NULL,
            completion_tokens BIGINT NOT NULL,
            total_tokens BIGINT NOT NULL,
            cost_usd DOUBLE PRECISION NOT NULL,
            call_count INTEGER NOT NULL,
            failed_call_count INTEGER NOT NULL,
            duration_ms BIGINT NOT NULL,
            status TEXT NOT NULL,
            failure_code TEXT NULL,
            provider TEXT NULL,
            prompt_version TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(run_id,user_id,agent,layer,model),
            FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id)
        )
        """
    )
    _execute("ALTER TABLE agent_run_archive ADD COLUMN IF NOT EXISTS failure_code TEXT NULL")
    _execute("ALTER TABLE agent_run_archive ADD COLUMN IF NOT EXISTS provider TEXT NULL")
    _execute("ALTER TABLE agent_run_archive ADD COLUMN IF NOT EXISTS prompt_version TEXT NULL")
    _execute("CREATE INDEX IF NOT EXISTS idx_agent_run_archive_owner_agent_created ON agent_run_archive(user_id,agent,created_at DESC)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_page_leases (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            lease_token_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(user_id,lease_token_hash)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_monitor_page_leases_active ON monitor_page_leases(user_id,session_id,symbol,expires_at)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_threads (
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            messages JSONB NOT NULL DEFAULT '[]'::jsonb,
            message_count INTEGER NOT NULL DEFAULT 0,
            last_message_preview TEXT NOT NULL DEFAULT '',
            pinned BOOLEAN NOT NULL DEFAULT false,
            archived BOOLEAN NOT NULL DEFAULT false,
            migration_batch_id UUID NULL REFERENCES legacy_import_batches(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(user_id,session_id)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_conversation_threads_owner_updated ON conversation_threads(user_id,archived,updated_at DESC)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            user_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            migration_batch_id UUID NULL REFERENCES legacy_import_batches(id),
            added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(user_id,ticker)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_watchlist_items_owner_added ON watchlist_items(user_id,added_at,ticker)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            ticker TEXT NULL,
            title TEXT NULL,
            summary TEXT NULL,
            tags JSONB NULL,
            generated_at TIMESTAMPTZ NULL,
            confidence_score DOUBLE PRECISION NULL,
            is_favorite BOOLEAN NOT NULL DEFAULT false,
            trace_digest JSONB NOT NULL DEFAULT '{}'::jsonb,
            report JSONB NOT NULL,
            quality_state TEXT NOT NULL DEFAULT 'pass',
            publishable BOOLEAN NOT NULL DEFAULT true,
            quality_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_type TEXT NOT NULL DEFAULT 'ai_generated',
            filing_type TEXT NULL,
            publisher TEXT NULL,
            share_token TEXT NULL,
            shared_at TIMESTAMPTZ NULL,
            migration_batch_id UUID NULL REFERENCES legacy_import_batches(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_reports_owner_created ON reports(user_id,created_at DESC)")
    _execute("CREATE INDEX IF NOT EXISTS idx_reports_owner_session_generated ON reports(user_id,session_id,generated_at DESC)")
    _execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_reports_share_token ON reports(share_token) WHERE share_token IS NOT NULL")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS report_citations (
            id BIGSERIAL PRIMARY KEY,
            report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source_id TEXT NULL,
            title TEXT NULL,
            url TEXT NULL,
            snippet TEXT NULL,
            published_date TEXT NULL,
            confidence DOUBLE PRECISION NULL,
            citation JSONB NOT NULL,
            migration_batch_id UUID NULL REFERENCES legacy_import_batches(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(report_id,source_id)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_report_citations_owner_report ON report_citations(user_id,report_id,id)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_comments (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            level TEXT NOT NULL,
            text TEXT NOT NULL,
            trigger_kind TEXT NOT NULL,
            trigger_detail TEXT NOT NULL,
            trigger_observed_at TEXT NOT NULL,
            trigger_fingerprint TEXT NOT NULL,
            source TEXT NOT NULL,
            escalated BOOLEAN NOT NULL,
            prediction_id UUID NULL,
            UNIQUE(user_id,session_id,trigger_fingerprint),
            FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_monitor_comments_tenant_time ON monitor_comments(user_id,session_id,symbol,ts DESC,id DESC)")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage (
            id BIGSERIAL PRIMARY KEY,
            run_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            logical_role TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NULL,
            prediction_id UUID NULL,
            prompt_tokens BIGINT NOT NULL DEFAULT 0,
            completion_tokens BIGINT NOT NULL DEFAULT 0,
            total_tokens BIGINT NOT NULL DEFAULT 0,
            cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            latency_ms BIGINT NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error_code TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(run_id,user_id,logical_role,attempt),
            FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id)
        )
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_owner_created ON llm_usage(user_id,created_at DESC)")
    _execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_run ON llm_usage(user_id,run_id,logical_role,attempt)")


def downgrade() -> None:
    # 既有四张生产表属于本 revision 之前的运行时 schema，回滚时保留其数据。
    _execute("DROP TABLE IF EXISTS llm_usage")
    _execute("DROP TABLE IF EXISTS monitor_comments")
    _execute("DROP TABLE IF EXISTS report_citations")
    _execute("DROP TABLE IF EXISTS reports")
    _execute("DROP TABLE IF EXISTS watchlist_items")
    _execute("DROP TABLE IF EXISTS conversation_threads")
    _execute("DROP TABLE IF EXISTS legacy_import_batches")
    _execute("DROP INDEX IF EXISTS uq_agent_predictions_idempotency")
    _execute("ALTER TABLE agent_predictions DROP COLUMN IF EXISTS evidence_as_of")
    _execute("ALTER TABLE agent_predictions DROP COLUMN IF EXISTS evidence_provider")
    _execute("ALTER TABLE agent_predictions DROP COLUMN IF EXISTS prompt_version")
    _execute("ALTER TABLE agent_prediction_outcomes DROP COLUMN IF EXISTS algorithm_version")
    _execute("ALTER TABLE agent_prediction_outcomes DROP COLUMN IF EXISTS market_as_of")
    _execute("ALTER TABLE agent_prediction_outcomes DROP COLUMN IF EXISTS market_provider")
    _execute("ALTER TABLE agent_run_archive DROP COLUMN IF EXISTS prompt_version")
    _execute("ALTER TABLE agent_run_archive DROP COLUMN IF EXISTS provider")
    _execute("ALTER TABLE agent_run_archive DROP COLUMN IF EXISTS failure_code")
