import pytest
from closegraph.api.auth import LocalAuth, DevAccount
from closegraph.collections.presentation import actor_name
from closegraph.services.review import independent
from closegraph.services.errors import DomainError


def test_four_separate_business_identities_and_passwords():
    names = [('accountant', 'PREPARER'), ('account_manager', 'REVIEWER'),
             ('fund_manager', 'FUND_MANAGER'), ('investor', 'INVESTOR')]
    auth = LocalAuth(accounts=[DevAccount.create(name, name+'-password', role, ()) for name, role in names])
    for name, role in names:
        token, principal = auth.login(name, name+'-password')
        assert principal.actor.actor_id == name and principal.actor.role == role
        assert auth.resolve(token).actor == principal.actor
        for other, _ in names:
            if other != name:
                assert auth.login(other, name+'-password') is None
    assert auth.login('preparer', 'accountant-password') is None
    assert auth.login('reviewer', 'account_manager-password') is None
    assert actor_name('preparer') == 'Accountant'
    assert actor_name('reviewer') == 'Account manager'


@pytest.mark.parametrize('old,new', [('preparer','accountant'), ('reviewer','account_manager')])
def test_renamed_identity_cannot_approve_its_own_historical_work(old, new):
    for state in ({'contributors':[old]}, {'prepared_by':old}):
        with pytest.raises(DomainError):
            independent(state, new)
    independent({'contributors':['accountant']}, 'account_manager')
