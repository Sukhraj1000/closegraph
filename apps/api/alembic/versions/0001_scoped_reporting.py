"""Initial immutable scoped reporting schema and PostgreSQL history guards."""
from alembic import op
from closegraph.storage.models import Base, APPEND_ONLY_MODELS

revision = "0001_scoped_reporting"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Reporting persistence requires PostgreSQL")
    Base.metadata.create_all(bind)
    op.execute("""CREATE FUNCTION closegraph_reject_history_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'CloseGraph historical records are append-only';
    END; $$""")
    for model in APPEND_ONLY_MODELS:
        table = model.__tablename__
        op.execute(f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION closegraph_reject_history_mutation()")


def downgrade():
    for model in APPEND_ONLY_MODELS:
        op.execute(f"DROP TRIGGER IF EXISTS immutable_history ON {model.__tablename__}")
    op.execute("DROP FUNCTION IF EXISTS closegraph_reject_history_mutation()")
    Base.metadata.drop_all(op.get_bind())
