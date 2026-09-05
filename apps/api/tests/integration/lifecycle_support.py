"""Small synthetic fixtures for pure lifecycle contract tests, never runtime data."""
from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook

from closegraph.services.lifecycle import LifecycleService
from closegraph.services.repository import MemoryRepository,MemoryBlobs,MemoryAuthorizer


class SourceEvaluator:
    required_check_ids=("fee",)
    def __call__(self,state,blobs):
        facts={f["fact_id"]:f for f in state["facts"]}
        expected=Decimal(blobs.get(state["evidence"]["fee-source"]["content_hash"]).decode())
        fee=Decimal(facts["fee"]["value_decimal"])
        gross=Decimal(facts["gross"]["value_decimal"])
        return {"checks":[{"id":"fee","required":True,"status":"PASS" if fee==expected else "FAIL",
                           "detail":"Actual source fee tie-out","difference":str(fee-expected),"tolerance":"0"}],
                "values":{"gross":str(gross),"fee":str(fee),"total":format(gross-fee,".2f")}}


def synthetic_service():
    repository,blobs=MemoryRepository(),MemoryBlobs()
    authorizer=MemoryAuthorizer({
        ("preparer","synthetic-fund"):{"inspect","download","correct","recompute","invalidate"},
        ("reviewer","synthetic-fund"):{"inspect","download","review","reject","publish"},
    })
    workbook=Workbook(); sheet=workbook.active;sheet.title="Pack"
    sheet.append(["SYNTHETIC reporting pack","Amount"])
    sheet.append(["Gross",1000]);sheet.append(["Fee",20]);sheet.append(["Net",980])
    stream=BytesIO();workbook.save(stream)
    template_hash=blobs.put(stream.getvalue())
    evidence={}
    for source_id,fact_id,content in (("gross-source","gross",b"1000.00"),("fee-source","fee",b"10.00")):
        evidence[source_id]={"source_version":1,"content_hash":blobs.put(content),
            "locator":{"kind":"csv","row":1,"column":"value"},"fact_ids":[fact_id],
            "entity_id":"synthetic-entity","period":"2026-Q2","currency":"GBP"}
    state={"tenant_id":"synthetic-tenant","fund_id":"synthetic-fund","pack_id":"synthetic-pack","version":1,
        "prepared_by":"preparer","contributors":["preparer"],"facts":[
            {"fact_id":fact_id,"fact_version":1,"metric":fact_id,"value_decimal":value,
             "entity_id":"synthetic-entity","period":"2026-Q2","currency":"GBP","raw_value":value,"raw_scale":"1",
             "source":{"source_id":source}}
            for fact_id,value,source in (("gross","1000.00","gross-source"),("fee","20.00","fee-source"))],
        "evidence":evidence,"source_versions":{source:1 for source in evidence},
        "rule_version":"synthetic-v1","mapping_version":"synthetic-v1","policy_version":"native-single-parser-v1",
        "dependency_edges":[["gross","output"],["fee","output"]],"dependency_coverage":True,
        "template":{"template_hash":template_hash,"version":"value-only-v1",
                    "bindings":[["gross","Pack","B2"],["fee","Pack","B3"],["total","Pack","B4"]]},
        "observations":[{"primary":{},"secondary":None,"availability":"NOT_RUN"}],"native":True,
        "checks":[{"id":"fee","status":"FAIL","required":True,"detail":"20 differs from source 10"}],"values":{},
        "history":[],"freshness":"CURRENT","execution_status":"COMPLETED","routing_status":"BLOCKED",
        "review_status":"PENDING","publications":[]}
    repository.create(state)
    return LifecycleService(repository,blobs,authorizer,SourceEvaluator())


def repair(service):
    state=service.inspect("synthetic-pack",actor="preparer",scope="synthetic-fund")
    corrected=service.correct("synthetic-pack",actor="preparer",scope="synthetic-fund",expected_version=state["version"],
        fact_id="fee",value_decimal="10.00",reason="Read synthetic source fee",source_id="fee-source")
    return service.recompute("synthetic-pack",actor="preparer",scope="synthetic-fund",expected_version=corrected["version"])


def approve(service,state):
    return service.review("synthetic-pack",actor="reviewer",scope="synthetic-fund",expected_version=state["version"],
                          note="Compared original source and recomputed output",attested=True)
