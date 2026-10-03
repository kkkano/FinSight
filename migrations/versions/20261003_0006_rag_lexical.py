"""允许显式词法文档不带向量，保留所有既有数据。"""
from alembic import op

revision = "20261003_0006"
down_revision = "20261003_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE rag_documents_v2 ALTER COLUMN embedding DROP NOT NULL")


def downgrade():
    raise RuntimeError("保留词法文档；回滚应用时无需删除文档或恢复向量非空约束。")
