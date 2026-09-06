"""Business account identities, including display of immutable historical records."""
LEGACY_ACCOUNTS = {'preparer': 'accountant', 'reviewer': 'account_manager'}

def canonical_actor(actor_id):
    return LEGACY_ACCOUNTS.get(actor_id, actor_id)

def actor_name(actor_id):
    actor_id = canonical_actor(actor_id)
    return {'accountant': 'Accountant', 'account_manager': 'Account manager',
            'fund_manager': 'Fund manager', 'investor': 'Investor'}.get(actor_id, actor_id.replace('_', ' ').title())
