"""Declared synthetic relationships, scoped operands and isolated Decimal math."""
from decimal import Decimal, localcontext
from closegraph.extraction.numbers import parse_decimal, DECIMAL_CONTEXT, NumericError


def reconcile(facts, rule):
    index={}
    for fact in facts: index.setdefault(fact.get('metric'),[]).append(fact)
    scope=('entity_id','period','currency')
    def operand(metric):
        entries=index.get(metric,[])
        if len(entries)!=1: raise ValueError('Missing or duplicate operand: '+metric)
        fact=entries[0]
        if any(fact.get(k)!=rule.get(k) or not rule.get(k) for k in scope): raise ValueError('Operand context mismatch: '+metric)
        if fact.get('interpretation_status') not in {'RULE_MAPPED','CORRECTED'}: raise ValueError('Unresolved operand: '+metric)
        value=parse_decimal(fact.get('value_decimal'))
        if value is None: raise ValueError('Missing value: '+metric)
        return value
    def check(identity,metrics,calculation,actual_metric,*,optional=False):
        c=dict(id=identity,required=True,rule_version=rule.get('version'),tolerance_version=rule.get('tolerance_version'),fact_ids=[f['fact_id'] for m in metrics for f in index.get(m,[])],operands=[{k:f.get(k) for k in ('fact_id','metric','value_decimal',*scope)} for m in metrics for f in index.get(m,[])])
        if optional and all(m not in index for m in metrics):
            return {**c,'status':'NOT_APPLICABLE','applicable':False,'justification':'The declared fixture has no balance-sheet section.'}
        try:
            if rule.get('approved') is not True or not rule.get('approval_id') or not rule.get('version') or not rule.get('tolerance_version'):
                raise ValueError('Approved versioned rule and tolerance required')
            tolerance=parse_decimal(rule.get('tolerance'))
            if tolerance is None or tolerance<0: raise ValueError('Invalid tolerance')
            with localcontext(DECIMAL_CONTEXT):
                expected=calculation(operand); actual=operand(actual_metric); delta=actual-expected
                c.update(status='PASS' if abs(delta)<=tolerance else 'FAIL',expected_decimal=format(expected,'f'),actual_decimal=format(actual,'f'),delta_decimal=format(delta,'f'),tolerance_decimal=format(tolerance,'f'),diagnostics=[])
        except (ValueError,NumericError) as error:
            c.update(status='UNKNOWN',diagnostics=[str(error)])
        return c
    return [
        check('fee',('capital','fee_rate','fee'),lambda get:get('capital')*get('fee_rate'),'fee'),
        check('source_to_pack',('fee','statement_fee'),lambda get:get('fee'),'statement_fee'),
        check('balance_sheet',('assets','liabilities','equity'),lambda get:get('liabilities')+get('equity'),'assets',optional=True),
    ]
