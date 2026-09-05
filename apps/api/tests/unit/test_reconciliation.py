from copy import deepcopy
from decimal import localcontext
from closegraph.validators.financial import reconcile


def facts():
    return [dict(fact_id=m,metric=m,value_decimal=v,entity_id='0012',period='2026-Q1',currency='GBP',interpretation_status='RULE_MAPPED',interpretation_rule_id='synthetic-template-v1') for m,v in [('capital','12000000'),('fee_rate','0.005'),('fee','75000'),('statement_fee','75000')]]


def rule():
    return dict(approved=True,version='fictional-fee-v1',approval_id='synthetic-approved',entity_id='0012',period='2026-Q1',currency='GBP',tolerance='0.01',tolerance_version='penny-v1')


def test_decimal_fee_and_multi_operand_diagnostics():
    with localcontext() as ctx:
        ctx.prec=3
        result=reconcile(facts(),rule())
    fee=next(c for c in result if c['id']=='fee')
    assert fee['status']=='FAIL' and fee['expected_decimal']=='60000.000'
    assert set(fee['fact_ids'])=={'capital','fee_rate','fee'}
    assert 'culprit' not in fee
    corrected=facts(); corrected[2]['value_decimal']='60000'
    checks={c['id']:c for c in reconcile(corrected,rule())}
    assert checks['fee']['status']=='PASS' and checks['source_to_pack']['status']=='FAIL'
    corrected[3]['value_decimal']='60000'
    assert all(c['status'] in ('PASS','NOT_APPLICABLE') for c in reconcile(corrected,rule()))


def test_context_duplicates_and_rule_ambiguity_never_pass():
    for mutation in ['scope','duplicate','missing','rule']:
        f=deepcopy(facts()); r=rule()
        if mutation=='scope': f[0]['period']='2025-Q1'
        if mutation=='duplicate': f.append(f[0])
        if mutation=='missing': f[0]['value_decimal']=None
        if mutation=='rule': r['approved']=False
        assert next(c for c in reconcile(f,r) if c['id']=='fee')['status']=='UNKNOWN'


def test_balance_sheet_unknown_if_partially_present():
    f=facts()+[dict(facts()[0],fact_id='assets',metric='assets',value_decimal='20')]
    check=next(c for c in reconcile(f,rule()) if c['id']=='balance_sheet')
    assert check['status']=='UNKNOWN'


def test_canonical_corrected_operands_are_allowed_but_missing_interpretation_is_unknown():
    corrected=facts()
    for fact in corrected[2:]:
        fact.update(value_decimal='60000',interpretation_status='CORRECTED',correction_id='recorded-correction')
    assert all(c['status'] in ('PASS','NOT_APPLICABLE') for c in reconcile(corrected,rule()))
    corrected[0].pop('interpretation_status')
    assert next(c for c in reconcile(corrected,rule()) if c['id']=='fee')['status']=='UNKNOWN'


def test_complete_balance_sheet_computes_exact_difference_and_pinned_tolerance():
    operands=facts()+[dict(facts()[0],fact_id=metric,metric=metric,value_decimal=value)
        for metric,value in [('assets','1000000.01'),('liabilities','750000'),('equity','250000')]]
    with localcontext() as context:
        context.prec=3
        check=next(row for row in reconcile(operands,rule()) if row['id']=='balance_sheet')
    assert check['status']=='PASS'
    assert check['expected_decimal']=='1000000' and check['delta_decimal']=='0.01'
    assert check['tolerance_version']=='penny-v1'
    assert set(check['fact_ids'])=={'assets','liabilities','equity'}
    operands[-3]['value_decimal']='1000000.02'
    failed=next(row for row in reconcile(operands,rule()) if row['id']=='balance_sheet')
    assert failed['status']=='FAIL' and failed['delta_decimal']=='0.02'
    assert 'culprit' not in failed and len(failed['operands'])==3
