"""Pure native pipeline stages over immutable receipts and explicit snapshots."""
from copy import deepcopy
from hashlib import sha256

import polars as pl

from closegraph.contracts import Scope
from closegraph.extraction.common import ExtractionError
from closegraph.extraction.context import normalise_fact
from closegraph.extraction.csv import CSVLayout, extract_csv
from closegraph.extraction.excel import ExcelLayout, extract_excel
from closegraph.extraction.numbers import NumericError, normalise_number
from closegraph.fixtures import BINDINGS, COLUMNS, CONTEXT, FEE_RULE, RULE
from closegraph.services.pdf_evidence import PdfEvidenceService
from closegraph.validators.coverage import coverage_check
from closegraph.validators.financial import reconcile
from closegraph.validators.schema import validate_rows

REQUIRED_CHECK_IDS=('data_schema','source_coverage','evidence','source_inputs','fee','source_to_pack','balance_sheet')
METRICS={'capital':('capital',),'fee-rule':('fee_rate',),'original':('fee','statement_fee')}


def ingest_sources(state, blobs, *, pdf_evidence=None, scope=None):
    latest={}
    for receipt in state.get('receipts',[]):
        role=receipt['source_id']
        if role not in latest or receipt['version']>latest[role]['version']: latest[role]=receipt
    observations=[]; dispositions=[]; rows=[]; facts=[]; evidence={}; sources={}; errors=[]; template={}
    errors.extend('Unsupported source role: '+role for role in latest if role not in {*METRICS, 'reporting-evidence'})
    old={f['fact_id']:f for f in state.get('facts',[])}
    rule=deepcopy(RULE); rule['approved']=False
    for role, role_metrics in METRICS.items():
        receipt=latest.get(role)
        if receipt is None:
            errors.append('Missing source role: '+role); continue
        content=blobs.get(receipt['content_hash'])
        if sha256(content).hexdigest()!=receipt['content_hash']: raise ExtractionError('hash_mismatch')
        try:
            if role=='original':
                result=extract_excel(content,document_version_id=receipt['document_version_id'],content_hash=receipt['content_hash'],layout=ExcelLayout('Pack',('A1','B2','B3','B4','B6','B7','B8')))
                values={o['source']['locator']['cell']:o['raw_value'] for o in result['observations']}
                if not str(values['A1']).startswith('SYNTHETIC') or any(values[a]!=CONTEXT[k] for a,k in [('B2','entity_id'),('B3','period'),('B4','currency')]):
                    raise ExtractionError('unsupported_template_context')
                observations.extend(result['observations']); dispositions.extend(result['dispositions'])
                selected=[o for o in result['observations'] if o['source']['locator']['cell'] in ('B6','B7')]
                for observation,metric in zip(selected,role_metrics):
                    observation.update(CONTEXT,metric=metric,raw_scale='units')
                    rows.append({**CONTEXT,'metric':metric,'value':observation['raw_value'],'scale':'units'})
                template={'template_hash':receipt['content_hash'],'bindings':BINDINGS,'version':'value-only-v1'}
            else:
                result=extract_csv(content,document_version_id=receipt['document_version_id'],content_hash=receipt['content_hash'],layout=CSVLayout(COLUMNS,COLUMNS))
                observations.extend(result['observations']); dispositions.extend(result['dispositions']); selected=result['observations']
                rows.extend(o['raw_values'] for o in selected if o['raw_values'])
                for observation in selected:
                    raw=observation['raw_values']
                    observation.update({k:raw.get(k) for k in ('entity_id','period','currency','metric')},raw_value=raw.get('value'),raw_scale=raw.get('scale'))
                if role=='fee-rule': rule['approved']=content==FEE_RULE
            preview=[]
            for observation in selected:
                metric=observation.get('metric'); oid=observation['occurrence_id']; source_id=role+':'+oid
                mapping={**CONTEXT,'approved':True,'approval_id':'synthetic-mapping-approved','version':'synthetic-template-v1','mapping':{m:m for m in role_metrics}}
                fact=normalise_fact(observation,mapping=mapping)
                if fact["interpretation_status"] == "RESOLVED":
                    fact["interpretation_status"] = "RULE_MAPPED"
                    fact["interpretation_rule_id"] = mapping["version"]
                fact_id=metric if metric in role_metrics else 'unresolved:'+oid
                # Duplicate metric occurrences retain distinct immutable identities and fail reconciliation.
                if any(f['fact_id']==fact_id for f in facts): fact_id=fact_id+':'+oid
                previous=old.get(fact_id)
                same_source=previous and previous.get('source',{}).get('document_version_id')==receipt['document_version_id'] and previous.get('occurrence_id')==oid
                fact.update(fact_id=fact_id,fact_version=(previous.get('fact_version',1)+1 if previous else 1),source={**fact['source'],'source_id':source_id})
                if previous and not same_source:
                    fact['supersedes'] = previous.get('fact_version',1)
                if same_source: fact=deepcopy(previous)
                facts.append(fact)
                preview.append({'label':metric or 'Unresolved record','value':str(observation.get('raw_value') or '')})
                evidence[source_id]={**CONTEXT,'source_version':receipt['version'],'document_version_id':receipt['document_version_id'],'source_id':role,'content_hash':receipt['content_hash'],'locator':observation['source']['locator'],'fact_ids':[fact_id],'filename':receipt['filename'],'preview_rows':preview.copy(),'authority_status':'APPROVED_SYNTHETIC_RULE' if role=='fee-rule' and rule['approved'] else 'OBSERVED'}
                sources[source_id]=receipt['version']
        except ExtractionError as error:
            errors.append(role+': '+error.code)
    # Persist the canonical occurrence/observation envelope alongside original raw tokens.
    by_occurrence={o['occurrence_id']:o for o in observations}
    canonical_observations=[]
    for item in dispositions:
        raw=by_occurrence[item['occurrence_id']]
        item['raw_content']=raw.get('raw_record') or str(raw.get('raw_value') or '')
        item['reason']='; '.join(item.get('reasons',[])) or None
        if item['source']['locator']['kind']=='csv':
            item['source']['locator']={'kind':'csv','row':item['source']['locator']['row'],'column':'value'}
        canonical_observations.append({'observation_id':'native:'+raw['occurrence_id'],'occurrence_id':raw['occurrence_id'],'parser':'native-'+raw['source']['locator']['kind'],'parser_version':'1','settings':{'raw_observation':deepcopy(raw)},'response_id':raw['source']['document_version_id'],'response_content_hash':raw['source']['content_hash'],'mode':'NATIVE','confidence':{'status':'NOT_APPLICABLE','value':None,'reason':'Declared native layout; no model probability','calibrated':False},'candidate':{k:raw.get(k) for k in ('metric','raw_value','raw_scale','entity_id','period','currency')}})
    for fact in facts:
        fact['observation_ids']=['native:'+fact['occurrence_id']]
        if fact['source']['locator']['kind']=='csv':
            fact['source']['locator']={'kind':'csv','row':fact['source']['locator']['row'],'column':'value'}
    for item in evidence.values():
        if item['locator']['kind']=='csv':
            item['locator']={'kind':'csv','row':item['locator']['row'],'column':'value'}
    # Rule and capital support the evidenced correction of both original output fields.
    for source_id,item in evidence.items():
        if item['source_id']=='capital' or (item['source_id']=='fee-rule' and rule['approved']):
            item['fact_ids']=sorted(set(item['fact_ids'])|{'fee','statement_fee'})
    pdf_report = None
    pdf_receipt = latest.get('reporting-evidence')
    if pdf_receipt is not None:
        content = blobs.get(pdf_receipt['content_hash'])
        if sha256(content).hexdigest() != pdf_receipt['content_hash']:
            raise ExtractionError('hash_mismatch')
        pdf_scope = scope or Scope(**{key: state[key] for key in ('tenant_id', 'fund_id', 'pack_id')})
        pdf = (pdf_evidence or PdfEvidenceService()).extract(
            pdf_receipt, content, scope=pdf_scope, blobs=blobs)
        facts.extend(pdf['facts'])
        evidence.update(pdf['evidence'])
        sources.update(pdf['source_versions'])
        canonical_observations.extend(pdf['extraction_observations'])
        pdf_report = pdf['report']
    frame=pl.DataFrame(rows,schema={c:pl.String for c in COLUMNS}) if rows else pl.DataFrame(schema={c:pl.String for c in COLUMNS})
    schema=validate_rows(frame)
    if errors: schema.update(status='FAIL',diagnostics=schema.get('diagnostics',[])+errors)
    coverage=coverage_check([o['occurrence_id'] for o in observations],dispositions)
    if errors: coverage.update(status='FAIL',diagnostics=coverage.get('diagnostics',[])+errors)
    if pdf_report is not None:
        # Native coverage is checked using its declared layout. PDF citations are
        # canonical typed anchors, with separate unresolved interpretation coverage.
        dispositions.extend(pdf['source_occurrences'])
        coverage.update(status='FAIL',
            diagnostics=coverage.get('diagnostics', []) + pdf_report['diagnostics'],
            pdf_occurrence_count=pdf_report['occurrence_count'],
            pdf_unresolved_count=pdf_report['unresolved_count'])
    patch = {'facts': facts,'evidence': evidence,'source_versions': sources,'source_occurrences': dispositions,'extraction_observations': canonical_observations,'extraction_report': {'schema':schema,'coverage':coverage,'errors':errors,'pdf':pdf_report},'rule': rule,'rule_version': rule['version'],'mapping_version': 'synthetic-template-v1','policy_version': 'native-single-parser-v1' if pdf_report is None else 'pdf-unmapped-evidence-v1','template': template,'native': pdf_report is None,'observations': [{'primary':f,'secondary':None,'availability':'NOT_RUN'} for f in facts],'dependency_edges': [[f['fact_id'],'output'] for f in facts]+[['rule','output'],['mapping','output'],['policy','output']],'dependency_coverage': pdf_report is None and not errors and len(facts)==4,'external_freshness': 'CURRENT'}


    configured = state.get('configured_records', {})
    permitted = {'rule', 'rule_version', 'mappings', 'mapping_version', 'template', 'policy', 'policy_version'}
    if not isinstance(configured, dict) or set(configured) - permitted:
        raise ExtractionError('invalid_pinned_configuration')
    changed_interpretation = any(
        key in configured and configured[key] != patch.get(key)
        for key in ('mappings', 'mapping_version', 'template'))
    patch.update(deepcopy(configured))
    if changed_interpretation:
        diagnostic = 'Pinned mapping/template requires a supported interpretation before source coverage can pass'
        schema.update(status='FAIL', diagnostics=schema.get('diagnostics', []) + [diagnostic])
        coverage.update(status='FAIL', diagnostics=coverage.get('diagnostics', []) + [diagnostic])
        patch['dependency_coverage'] = False
        for fact in facts:
            # Interpretation is part of an immutable fact version, even when
            # the underlying source bytes and displayed amount are unchanged.
            previous = old.get(fact['fact_id'])
            if (previous and fact.get('fact_version',1) == previous.get('fact_version',1)
                    and (fact.get('interpretation_status') != 'UNRESOLVED'
                         or fact.get('interpretation_rule_id') is not None)):
                fact['fact_version'] = previous.get('fact_version',1) + 1
                fact['supersedes'] = previous.get('fact_version',1)
            fact['interpretation_status'] = 'UNRESOLVED'
            fact['interpretation_rule_id'] = None
    return patch


def source_inputs_check(state, blobs):
    """Tie governing operands to immutable original native observations.

    A correction to an output value is checked against these pinned inputs. A
    correction to a rate/capital observation cannot authorize a new treatment;
    replacing the actual scoped source creates a new observed input version.
    """
    observations={item["observation_id"]:item for item in state.get("extraction_observations",[])}
    diagnostics=[]; operands=[]; unknown=False
    for metric in ("capital","fee_rate"):
        candidates=[f for f in state.get("facts",[]) if f.get("metric")==metric]
        if len(candidates)!=1:
            diagnostics.append("Missing or duplicate governing source operand: "+metric)
            unknown=True
            continue
        fact=candidates[0]
        selected=[observations[identity] for identity in fact.get("observation_ids",[]) if identity in observations]
        if len(selected)!=1 or selected[0].get("mode")!="NATIVE":
            diagnostics.append("Original native observation unavailable for "+metric)
            unknown=True
            continue
        observation=selected[0]
        original=observation.get("settings",{}).get("raw_observation",{})
        source=original.get("source",{})
        declared=state.get("evidence",{}).get(fact.get("source",{}).get("source_id"),{})
        if (source.get("document_version_id")!=fact.get("source",{}).get("document_version_id")
                or source.get("content_hash")!=declared.get("content_hash")):
            diagnostics.append("Governing observation source identity mismatch: "+metric)
            unknown=True
            continue
        # Verify that the pinned source is still available with its immutable hash.
        if sha256(blobs.get(source["content_hash"])).hexdigest()!=source["content_hash"]:
            diagnostics.append("Governing source integrity mismatch: "+metric)
            unknown=True
            continue
        try:
            expected=normalise_number(original.get("raw_value"),scale=original.get("raw_scale"))["value_decimal"]
        except NumericError:
            expected=None
        operands.append({"fact_id":fact["fact_id"],"metric":metric,"value_decimal":fact.get("value_decimal"),
                         "expected_source_decimal":expected,"observation_id":observation["observation_id"],
                         "document_version_id":source.get("document_version_id"),"raw_scale":original.get("raw_scale")})
        if expected is None or fact.get("value_decimal") is None:
            diagnostics.append("Governing input cannot be parsed from its original source: "+metric)
            unknown=True
        elif any(original.get(key)!=fact.get(key) for key in ("metric","entity_id","period","currency","raw_scale")):
            diagnostics.append("Governing input context/scale differs from its original source: "+metric)
        else:
            from decimal import Decimal
            if Decimal(expected)!=Decimal(fact["value_decimal"]):
                diagnostics.append("Governing input differs from its original source: "+metric)
    return {"id":"source_inputs","label":"Governing inputs match source evidence","required":True,
            "rule_version":"native-source-input-tieout-v1","status":"UNKNOWN" if unknown else "FAIL" if diagnostics else "PASS",
            "operands":operands,"diagnostics":diagnostics}


def evaluate_pack(state, blobs):
    report=state.get('extraction_report',{})
    checks=[deepcopy(report.get('schema',{'id':'data_schema','required':True,'status':'UNKNOWN'})),deepcopy(report.get('coverage',{'id':'source_coverage','required':True,'status':'UNKNOWN'}))]
    reasons=[]
    if not state.get('template') or not state.get('facts') or not state.get('rule',{}).get('approved'): reasons.append('Required template, facts or approved rule missing')
    for fact in state.get('facts',[]):
        source=state.get('evidence',{}).get(fact.get('source',{}).get('source_id'))
        if not source or fact.get('interpretation_status') not in {'RULE_MAPPED','CORRECTED'}: reasons.append('Required fact evidence/context unresolved: '+fact['fact_id'])
        elif sha256(blobs.get(source['content_hash'])).hexdigest()!=source['content_hash']: reasons.append('Source integrity mismatch')
    checks.append({'id': 'evidence','required': True,'status': 'FAIL' if reasons else 'PASS','diagnostics': reasons})
    checks.append(source_inputs_check(state,blobs))
    checks.extend(reconcile(state.get('facts',[]),state.get('rule',{})))
    values={f['metric']:f['value_decimal'] for f in state.get('facts',[]) if f['metric'] in ('fee','statement_fee') and f.get('value_decimal') is not None}
    if 'fee' in values: values['total']=values['fee']
    return {'checks':checks,'values':values,'total_label':'Total fee'}


evaluate_pack.required_check_ids=REQUIRED_CHECK_IDS
