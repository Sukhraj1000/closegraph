"""One local API process and one Dagster code location over durable PostgreSQL."""
import os
from pathlib import Path

from alembic.config import Config

from alembic import command
from closegraph.api.app import create_app
from closegraph.api.auth import DevAccount, LocalAuth
from closegraph.api.ports import Actor, DomainNotFound
from closegraph.api.services import PostgreSQLPackServices
from closegraph.contracts import Scope
from closegraph.fixtures import SCOPE
from closegraph.services.native import evaluate_pack
from closegraph.services.pdf_evidence import provider_from_environment
from closegraph.storage.blobs import LocalBlobStore
from closegraph.storage.database import make_engine, session_factory


def empty_state(*, pdf=False):
    state = {'title': 'Synthetic reporting pack · Q1 2026','facts': [],'evidence': {},'source_versions': {},'rule_version': 'fictional-fee-v1','mapping_version': 'synthetic-template-v1','policy_version': 'native-single-parser-v1','dependency_edges': [],'dependency_coverage': False,'template': {},'observations': [],'native': True,'checks': [],'values': {},'history': [],'freshness': 'STALE','execution_status': 'NOT_RUN','routing_status': 'BLOCKED','review_status': 'PENDING','contributors': ['preparer'],'publications': [],'candidate': None}

    state['priority_policy'] = {'version': 'synthetic-review-priority-v1', 'materiality_decimal': '50000', 'currency': 'GBP', 'impact_threshold': 2}
    if pdf:
        state.update(title='Synthetic PDF reporting evidence', native=False,
                     policy_version='pdf-unmapped-evidence-v1')
    return state


def development_scopes():
    return (Scope(**SCOPE), Scope(**{**SCOPE, 'pack_id': 'synthetic-pdf-pack'}))


def data_dir():
    return Path(os.environ.get('CLOSEGRAPH_DATA_DIR','.local/closegraph')).absolute()


def build_services(*,seed=False,migrate=False,pdf_provider=None):
    url=os.environ['CLOSEGRAPH_DATABASE_URL']
    scopes=development_scopes()
    accounts=[DevAccount.create(name,os.environ['CLOSEGRAPH_'+name.upper()+'_PASSWORD'],role,scopes) for name,role in [('preparer','PREPARER'),('reviewer','REVIEWER')]]
    accounts.extend(DevAccount.create(name,os.environ['CLOSEGRAPH_'+name.upper()+'_PASSWORD'],role,()) for name,role in [('fund_manager','FUND_MANAGER'),('investor','INVESTOR')] if os.environ.get('CLOSEGRAPH_'+name.upper()+'_PASSWORD'))
    auth=LocalAuth(accounts=accounts,collection_grants={a.username:{(scope.tenant_id,scope.fund_id) for scope in scopes} for a in accounts});engine=make_engine(url)
    from closegraph.collections.service import CollectionServices
    from closegraph.collections.provider import collection_pdf_provider
    if migrate:
        config=Config(str(Path(__file__).parents[2]/'alembic.ini'))
        with engine.begin() as connection:
            config.attributes['connection']=connection; command.upgrade(config,'head')
    services=PostgreSQLPackServices(session_factory(engine),LocalBlobStore(data_dir()/'blobs'),auth,evaluate_pack)
    services.pdf_evidence = pdf_provider if pdf_provider is not None else provider_from_environment(os.environ)
    services.collections=CollectionServices(session_factory(engine),LocalBlobStore(data_dir()/'collection-blobs',max_bytes=512*1024*1024),auth,pdf_provider=collection_pdf_provider(os.environ))
    if seed:
        actor=Actor(actor_id='preparer',role='PREPARER')
        for scope in scopes:
            try: services.get_pack(scope,actor)
            except DomainNotFound:
                services.create_pack(scope,actor,empty_state(pdf=scope.pack_id=='synthetic-pdf-pack'))
    return services


def app_factory():
    services=build_services(seed=True,migrate=True)
    return create_app(auth=services.auth,services=services,bind_host='127.0.0.1',allowed_origins=('http://127.0.0.1:24173','http://localhost:24173'),max_request_bytes=45*1024*1024)
