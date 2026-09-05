from closegraph.services.impact import dependency_impact

def test_transitive_closure_and_proven_independence():
    result=dependency_impact({"fee"},[("fee","nav"),("nav","statement"),("other","other-output")],{"statement","other-output"},coverage_complete=True)
    assert result.affected == frozenset({"fee","nav","statement"})
    assert result.independent == frozenset({"other-output"})
    assert not result.unverifiable

def test_unknown_and_cycle_never_claim_independence():
    for edges, complete in [([],False), ([("a","b"),("b","a")],True)]:
        result=dependency_impact({"a"},edges,{"output"},coverage_complete=complete)
        assert result.unverifiable and not result.independent
