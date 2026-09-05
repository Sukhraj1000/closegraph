"""Real process interruption, persistent Dagster state and PostgreSQL outbox recovery."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from dagster import DagsterInstance, DagsterRunStatus, build_sensor_context
from sqlalchemy import text, select, func
import pytest

from closegraph.api.auth import DevAccount, LocalAuth
from closegraph.api.ports import Actor
from closegraph.api.services import PostgreSQLPackServices
from closegraph.contracts import Scope, UploadRequest
from closegraph.fixtures import SCOPE, fixture_bytes
from closegraph.pipeline.definitions import build_definitions, run_request
from closegraph.pipeline.sensors import request_config
from closegraph.runtime import empty_state
from closegraph.services.native import evaluate_pack
from closegraph.storage.blobs import LocalBlobStore
from closegraph.storage.models import ProcessingResultRow


def configured(pg_sessions, tmp_path):
    scope = Scope(**SCOPE)
    actor = Actor(actor_id='preparer', role='PREPARER')
    auth = LocalAuth(accounts=[DevAccount.create('preparer', 'preparer-recovery-test', 'PREPARER', [scope])])
    services = PostgreSQLPackServices(pg_sessions, LocalBlobStore(tmp_path/'blobs'), auth, evaluate_pack)
    state = services.create_pack(scope, actor, empty_state())
    files = fixture_bytes()
    for role, name in [('capital', 'capital.csv'), ('fee-rule', 'fee-rule.csv'), ('original', 'original.xlsx')]:
        state = services.upload(scope, actor, UploadRequest(expected_version=state.version,
            idempotency_key=role, source_id=role, filename=name,
            media_type='text/csv' if name.endswith('.csv') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            content_base64=base64.b64encode(files[name]).decode()))
    return scope, actor, services


def dispatch(defs, instance):
    sensor = defs.resolve_sensor_def('committed_processing_requests')
    with build_sensor_context(instance=instance, repository_def=defs.get_repository_def()) as context:
        return sensor.evaluate_tick(context).run_requests


CHILD = r"""
import json,sys,time
from pathlib import Path
from dagster import DagsterInstance
from closegraph.api.auth import LocalAuth
from closegraph.api.services import PostgreSQLPackServices
from closegraph.storage.database import make_engine,session_factory
from closegraph.storage.blobs import LocalBlobStore
from closegraph.services.native import evaluate_pack
from closegraph.pipeline.definitions import build_definitions,run_request
from closegraph.pipeline.resources import RunScopedJSONIOManager
config=json.loads(Path(sys.argv[1]).read_text())
engine=make_engine(config['url'],connect_args={'options':'-csearch_path='+config['schema']})
services=PostgreSQLPackServices(session_factory(engine),LocalBlobStore(config['blobs']),LocalAuth(accounts=[]),evaluate_pack)
original=RunScopedJSONIOManager.handle_output
def stop_after_persist(self,context,obj):
 original(self,context,obj)
 if context.step_key==config['stage']:
  Path(config['marker']).write_text(json.dumps({'run_id':context.run_id,'stage_path':str(self.path_for(context))}))
  while True:time.sleep(1)
RunScopedJSONIOManager.handle_output=stop_after_persist
with DagsterInstance.from_config(config['dagster_home']) as instance:
 run_request(build_definitions(services,config['io']),instance,config['request'])
"""


@pytest.mark.parametrize('stage', ['processing_input', 'native_evaluation'])
def test_killed_worker_recovers_after_service_and_sensor_restart(pg_sessions, tmp_path, stage):
    scope, actor, services = configured(pg_sessions, tmp_path)
    home = tmp_path/'dagster'; home.mkdir(); (home/'dagster.yaml').write_text('telemetry:\n  enabled: false\n')
    io = tmp_path/'io'
    definitions = build_definitions(services, str(io))
    requests = services.pending_requests()
    target = requests[-1]
    with DagsterInstance.from_config(str(home)) as instance:
        for request in requests[:-1]:
            assert run_request(definitions, instance, request).success
    with pg_sessions() as session:
        schema = session.scalar(text('SELECT current_schema()'))
        url = session.bind.url.render_as_string(hide_password=False)
    marker = tmp_path/'interrupted.json'
    config = {'url':url, 'schema':schema, 'blobs':str(tmp_path/'blobs'), 'dagster_home':str(home),
              'io':str(io), 'marker':str(marker), 'request':target, 'stage':stage}
    config_file = tmp_path/'child-config.json'; config_file.write_text(json.dumps(config)); config_file.chmod(0o600)
    with (tmp_path/'child.log').open('w') as log:
        child = subprocess.Popen([sys.executable, '-c', CHILD, str(config_file)], stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+45
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline:
                time.sleep(.05)
            assert marker.exists(), (tmp_path/'child.log').read_text()[-5000:]
            interrupted = json.loads(marker.read_text())
            assert Path(interrupted['stage_path']).is_file()
            child.kill(); child.wait(timeout=10)
            assert child.returncode != 0
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
    # Reconstruct both facade and Dagster instance from durable state, like restart.
    restarted = PostgreSQLPackServices(pg_sessions, LocalBlobStore(tmp_path/'blobs'), services.auth, evaluate_pack)
    definitions = build_definitions(restarted, str(io))
    with DagsterInstance.from_config(str(home)) as instance:
        killed = instance.get_run_by_id(interrupted['run_id'])
        assert not killed.is_finished
        assert dispatch(definitions, instance) == []  # no stale-time/lease stealing
        # Equivalent to Dagster run monitoring after confirmed process death; the
        # test has actually SIGKILLed and waitpid-reaped the owner above.
        instance.report_run_failed(killed, 'Test supervisor confirmed killed owner exited')
        recovered = dispatch(definitions, instance)
        assert len(recovered) == 1 and recovered[0].run_key == target['request_id']+':1'
        # Recreating the sensor before dispatch yields the same durable identity.
        assert dispatch(build_definitions(restarted, str(io)), instance)[0].run_key == recovered[0].run_key
        result = definitions.resolve_job_def('process_reporting_pack').execute_in_process(
            instance=instance, run_config=recovered[0].run_config, tags=recovered[0].tags)
        assert result.success
        assert dispatch(definitions, instance) == []
        state = restarted.get_pack(scope, actor)
        assert state.execution_status == 'COMPLETED' and state.routing_status == 'BLOCKED'
        assert next(check for check in state.checks if check.id=='fee').status == 'FAIL'
        # Retrying delivery of the same immutable result cannot duplicate effects.
        with pg_sessions() as session:
            rows = session.scalars(select(ProcessingResultRow).filter_by(request_id=target['request_id'])).all()
            assert len(rows)==1
            replay = restarted.complete_processing(scope,target['request_id'],rows[0].result,result.run_id)
        assert replay['state'].version == state.version


def test_failed_before_claim_exhaustion_becomes_visible_and_terminal(pg_sessions, tmp_path):
    scope, actor, services = configured(pg_sessions, tmp_path)
    definitions = build_definitions(services, str(tmp_path/'io'))
    target = services.pending_requests()[-1]
    with DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        for request in services.pending_requests()[:-1]:
            assert run_request(definitions, instance, request).success
        for attempt in range(3):
            instance.create_run_for_job(definitions.resolve_job_def('process_reporting_pack'),
                status=DagsterRunStatus.FAILURE, run_config=request_config(target),
                tags={'closegraph/request':target['request_id'],'closegraph/attempt':str(attempt)})
        assert next(r for r in services.pending_requests() if r['request_id']==target['request_id'])['dagster_run_id'] is None
        assert dispatch(definitions, instance) == []
        assert services.pending_requests() == []
        state = services.get_pack(scope, actor)
        assert state.execution_status == 'FAILED' and state.routing_status == 'BLOCKED'
        assert 'exhausted' in state.execution_error
