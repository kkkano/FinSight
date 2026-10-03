"""新增研究运行终态与服务端权威消息，不改写既有会话。

Revision ID: 20261003_0005
Revises: 20260716_0004
"""
from __future__ import annotations

from alembic import op


revision = "20261003_0005"
down_revision = "20260716_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0")
    op.execute("""
        CREATE TABLE research_runs (
            sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            user_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            query TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            assistant_message_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            worker_id TEXT NOT NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            final_payload JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ NULL,
            PRIMARY KEY (user_id,run_id),
            UNIQUE (user_id,session_id,assistant_message_id),
            CONSTRAINT fk_research_runs_thread FOREIGN KEY (user_id,session_id)
                REFERENCES conversation_threads(user_id,session_id) ON DELETE CASCADE,
            CONSTRAINT ck_research_runs_status CHECK
                (status IN ('running','completed','failed','cancelled','interrupted','persistence_failed')),
            CONSTRAINT ck_research_runs_terminal CHECK
                ((status = 'running' AND completed_at IS NULL AND final_payload IS NULL)
                 OR (status <> 'running' AND completed_at IS NOT NULL AND final_payload IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX idx_research_runs_session ON research_runs(user_id,session_id,created_at)")
    op.execute("CREATE INDEX idx_research_runs_lease ON research_runs(lease_expires_at) WHERE status='running'")
    op.execute("""
        CREATE TABLE conversation_messages (
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user','assistant')),
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id,session_id,message_id),
            UNIQUE (user_id,run_id,role),
            CONSTRAINT fk_conversation_messages_thread FOREIGN KEY (user_id,session_id)
                REFERENCES conversation_threads(user_id,session_id) ON DELETE CASCADE,
            CONSTRAINT fk_conversation_messages_run FOREIGN KEY (user_id,run_id)
                REFERENCES research_runs(user_id,run_id) ON DELETE CASCADE
        )
    """)
    for table in ("research_runs", "conversation_messages"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner ON {table} FOR ALL
            USING (user_id = (SELECT current_setting('app.current_user_id', true)))
            WITH CHECK (user_id = (SELECT current_setting('app.current_user_id', true)))
        """)
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")


def downgrade() -> None:
    # 已交付的研究终态不能因应用回滚而删除；旧版本可忽略新增结构。
    raise RuntimeError("research delivery migration is forward-only; roll back application images without deleting user data")
