"""Human labels for legacy local demo accounts; immutable actor IDs stay intact."""
def actor_name(actor_id):
    return {'preparer': 'Accountant', 'reviewer': 'Account manager',
            'fund_manager': 'Fund manager', 'investor': 'Investor'}.get(actor_id, actor_id.replace('_', ' ').title())
