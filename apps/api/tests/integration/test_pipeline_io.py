from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
from dagster import AssetKey, build_output_context, build_input_context

from closegraph.pipeline.resources import RunScopedJSONIOManager


def output(run,step="native_evaluation",name="result",mapping=None):
    return build_output_context(run_id=run,step_key=step,name=name,mapping_key=mapping,asset_key=AssetKey(step))


def test_parallel_unpartitioned_assets_are_isolated_by_run(tmp_path):
    manager=RunScopedJSONIOManager(tmp_path)
    contexts=[output("run-a"),output("run-b")]
    barrier=Barrier(2)
    def process(index):
        context=contexts[index]
        manager.handle_output(context,{"pack_id":"pack-"+str(index),"snapshot_version":index+1})
        barrier.wait()
        return manager.load_input(build_input_context(upstream_output=context))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(process,range(2)))
    assert results==[{"pack_id":"pack-0","snapshot_version":1},{"pack_id":"pack-1","snapshot_version":2}]
    assert manager.path_for(contexts[0])!=manager.path_for(contexts[1])
    assert len(list(tmp_path.glob("*.json")))==2


def test_step_and_mapping_identities_are_distinct_and_survive_restart(tmp_path):
    first=RunScopedJSONIOManager(tmp_path)
    contexts=[output("run","extract"),output("run","evaluate"),output("run","evaluate",mapping="second")]
    for index,context in enumerate(contexts):
        first.handle_output(context,{"index":index})
    restarted=RunScopedJSONIOManager(tmp_path)
    assert [restarted.load_input(build_input_context(upstream_output=context)) for context in contexts]==[
        {"index":0},{"index":1},{"index":2}]


def test_corrupt_or_mismatched_stage_envelope_fails_closed(tmp_path):
    manager=RunScopedJSONIOManager(tmp_path)
    context=output("run-a")
    manager.handle_output(context,{"facts":["original"]})
    path=manager.path_for(context)
    envelope=json.loads(path.read_bytes())
    envelope["payload"]["facts"]=["tampered"]
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match="integrity"):
        manager.load_input(build_input_context(upstream_output=context))
    manager.handle_output(context,{"facts":["original"]})
    envelope=json.loads(path.read_bytes())
    envelope["identity"][0]="different-run"
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match="identity"):
        manager.load_input(build_input_context(upstream_output=context))
