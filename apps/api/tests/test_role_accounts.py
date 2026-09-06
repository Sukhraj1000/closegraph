import pytest
from closegraph.api.auth import LocalAuth,DevAccount
from closegraph.collections.presentation import actor_name

def test_business_login_names_preserve_identity_permissions_and_existing_sessions():
    accounts=[DevAccount.create('preparer','accountant-password','PREPARER',()),DevAccount.create('reviewer','manager-password','REVIEWER',())]
    auth=LocalAuth(accounts=accounts,login_aliases={'accountant':'preparer','account_manager':'reviewer'})
    for alias,original,password,role in [('accountant','preparer','accountant-password','PREPARER'),('account_manager','reviewer','manager-password','REVIEWER')]:
        token,principal=auth.login(alias,password)
        assert principal.actor.actor_id==original and principal.actor.role==role
        assert auth.resolve(token).actor==principal.actor
        assert auth.login(original,password)[1].actor==principal.actor
    assert auth.login('account_manager','accountant-password') is None
    assert auth.login('investor','accountant-password') is None
    assert actor_name('preparer')=='Accountant' and actor_name('reviewer')=='Account manager'

def test_alias_cannot_shadow_another_account_or_invent_access():
    account=DevAccount.create('preparer','accountant-password','PREPARER',())
    for aliases in ({'preparer':'preparer'},{'account_manager':'absent'}):
        with pytest.raises(ValueError):LocalAuth(accounts=[account],login_aliases=aliases)
