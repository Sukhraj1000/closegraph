"""Occurrence accounting includes rejected records and validates their anchors."""
from collections import Counter
from closegraph.extraction.common import valid_source


def coverage_check(expected_ids, dispositions):
    expected,actual=Counter(expected_ids),Counter(d.get('occurrence_id') for d in dispositions)
    reasons=[]
    if not expected: reasons.append('No expected source occurrences')
    if any(v!=1 for v in expected.values()) or any(v!=1 for v in actual.values()):
        reasons.append('Duplicate occurrence identity')
    if expected!=actual: reasons.append('Missing or unexpected source occurrences')
    if any(not valid_source(d.get('source')) for d in dispositions): reasons.append('Malformed evidence anchor')
    if any(d.get('disposition')!='ACCEPTED' for d in dispositions): reasons.append('Unresolved or rejected source record')
    return dict(id='source_coverage',required=True,status='FAIL' if reasons else 'PASS',diagnostics=reasons,expected_count=sum(expected.values()),observed_count=sum(actual.values()))
