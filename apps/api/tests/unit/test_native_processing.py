from copy import deepcopy
from hashlib import sha256
from closegraph.fixtures import fixture_bytes, SCOPE
from closegraph.services.native import ingest_sources, evaluate_pack


class Blobs:
    def __init__(self): self.objects={}
    def get(self,key): return self.objects[key]
    def put(self,data):
        key=sha256(data).hexdigest(); self.objects[key]=data; return key


def source_state():
    blobs=Blobs(); receipts=[]
    for role,name in [('capital','capital.csv'),('fee-rule','fee-rule.csv'),('original','original.xlsx')]:
        content=fixture_bytes()[name]; key=blobs.put(content)
        receipts.append(dict(source_id=role,document_version_id=role+'-v1',version=1,content_hash=key,storage_key=key,filename=name))
    state=dict(SCOPE,version=4,receipts=receipts,facts=[],evidence={},source_versions={})
    return state,blobs


def test_all_latest_receipts_ingest_and_two_step_repair_preserves_observations():
    state,blobs=source_state(); patch=ingest_sources(state,blobs); state.update(patch)
    result=evaluate_pack(state,blobs)
    assert next(c for c in result['checks'] if c['id']=='fee')['status']=='FAIL'
    assert result['values']['total']=='75000'
    assert len(state['facts'])==4 and state['dependency_coverage'] is True
    assert all(f['interpretation_status']=='RULE_MAPPED' and f['interpretation_rule_id'] for f in state['facts'])
    original=deepcopy(state['extraction_observations'])
    fee=next(f for f in state['facts'] if f['metric']=='fee'); fee.update(value_decimal='60000',fact_version=2,correction_source_id=fee['source']['source_id'],interpretation_status='CORRECTED',correction_id='fee-correction-v2')
    checks={c['id']:c for c in evaluate_pack(state,blobs)['checks']}
    assert checks['fee']['status']=='PASS' and checks['source_to_pack']['status']=='FAIL'
    repeated=ingest_sources(state,blobs)
    assert next(f for f in repeated['facts'] if f['metric']=='fee')['value_decimal']=='60000'
    assert repeated['extraction_observations']==original
    next(f for f in state['facts'] if f['metric']=='statement_fee')['value_decimal']='60000'
    checks={c['id']:c for c in evaluate_pack(state,blobs)['checks']}
    assert checks['fee']['status']==checks['source_to_pack']['status']=='PASS'


def test_missing_source_and_unapproved_rule_stay_visible():
    state,blobs=source_state(); state['receipts']=state['receipts'][:1]
    state.update(ingest_sources(state,blobs))
    checks={c['id']:c for c in evaluate_pack(state,blobs)['checks']}
    assert checks['fee']['status']=='UNKNOWN' and checks['evidence']['status']=='FAIL'


def test_governing_rate_and_capital_corrections_cannot_override_immutable_source_inputs():
    from closegraph.services.corrections import corrected_facts
    for metric,value,fee in [("fee_rate","0.006","72000"),("capital","14000000","70000")]:
        state,blobs=source_state()
        state.update(ingest_sources(state,blobs))
        source=next(key for key,item in state["evidence"].items() if metric in item["fact_ids"])
        state["facts"],_=corrected_facts(state["facts"],fact_id=metric,value_decimal=value,
            reason="Claim a different governing value",source_id=source,evidence=state["evidence"])
        rate_source=next(key for key,item in state["evidence"].items() if item["source_id"]=="fee-rule")
        for output in ("fee","statement_fee"):
            state["facts"],_=corrected_facts(state["facts"],fact_id=output,value_decimal=fee,
                reason="Recompute from changed governing value",source_id=rate_source,evidence=state["evidence"])
        checks={c["id"]:c for c in evaluate_pack(state,blobs)["checks"]}
        assert checks["fee"]["status"]==checks["source_to_pack"]["status"]=="PASS"
        assert checks["source_inputs"]["status"]=="FAIL"
        assert any(metric in reason for reason in checks["source_inputs"]["diagnostics"])


def test_real_source_replacement_pins_new_governing_input_and_keeps_old_observations():
    state,blobs=source_state()
    state.update(ingest_sources(state,blobs))
    original=deepcopy(state["extraction_observations"])
    latest=dict(state["receipts"][0],version=2,document_version_id="capital-v2")
    data=b"entity_id,period,currency,metric,value,scale\n0012,2026-Q1,GBP,capital,14000000,units\n"
    latest.update(content_hash=blobs.put(data),storage_key=blobs.put(data))
    state["receipts"].append(latest)
    state.update(ingest_sources(state,blobs))
    capital=next(f for f in state["facts"] if f["metric"]=="capital")
    assert capital["value_decimal"]=="14000000" and capital["fact_version"]==2
    assert next(c for c in evaluate_pack(state,blobs)["checks"] if c["id"]=="source_inputs")["status"]=="PASS"
    assert original[0]["settings"]["raw_observation"]["raw_value"]=="12000000"


def test_unknown_uploaded_role_is_visible_and_blocks_supported_pack():
    state,blobs=source_state()
    extra=dict(state["receipts"][0],source_id="unsupported",document_version_id="extra-v1")
    state["receipts"].append(extra)
    state.update(ingest_sources(state,blobs))
    assert "Unsupported source role: unsupported" in state["extraction_report"]["errors"]
    assert state["dependency_coverage"] is False
    checks={c["id"]:c for c in evaluate_pack(state,blobs)["checks"]}
    assert checks["source_coverage"]["status"]=="FAIL"


def test_all_material_native_facts_and_evidence_use_canonical_locators():
    from closegraph.contracts import SourceRef
    state,blobs=source_state()
    state.update(ingest_sources(state,blobs))
    for item in state["evidence"].values():
        SourceRef(document_version_id=item["document_version_id"],content_hash=item["content_hash"],locator=item["locator"])
