"""Add versioned collections and durable processing requests."""
from alembic import op
import sqlalchemy as sa
revision = '0002_collections'
down_revision = '0001_scoped_reporting'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('collections',
        sa.Column('id',sa.String(64),primary_key=True),sa.Column('tenant_id',sa.String(256),nullable=False),
        sa.Column('fund_id',sa.String(256),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('state',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_collections_tenant_id','collections',['tenant_id'])
    op.create_index('ix_collections_fund_id','collections',['fund_id'])
    op.create_table('collection_revisions',sa.Column('collection_id',sa.String(64),primary_key=True),
        sa.Column('version',sa.Integer(),primary_key=True),sa.Column('actor_id',sa.String(256),nullable=False),
        sa.Column('event_type',sa.String(64),nullable=False),sa.Column('detail',sa.JSON(),nullable=False),
        sa.Column('state',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['collection_id'],['collections.id'],ondelete='RESTRICT'))
    op.create_table('collection_jobs',sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('collection_id',sa.String(64),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('kind',sa.String(32),nullable=False),sa.Column('status',sa.String(32),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('result',sa.JSON(),nullable=True),
        sa.Column('dagster_run_id',sa.String(256),nullable=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['collection_id','version'],['collection_revisions.collection_id','collection_revisions.version'],ondelete='RESTRICT'))
    op.create_index('ix_collection_jobs_collection_id','collection_jobs',['collection_id'])
    op.execute('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON collection_revisions FOR EACH ROW EXECUTE FUNCTION closegraph_reject_history_mutation()')

def downgrade():
    raise RuntimeError('Collection source/review history must be preserved; downgrade requires an explicit archival migration')
