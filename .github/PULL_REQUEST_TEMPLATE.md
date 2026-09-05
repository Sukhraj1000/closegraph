## Linked scope

Refs #<task> (use Closes only when the whole task is implemented and verified).
Parent epic: #<epic>. OpenSpec task: <exact ID>.

## Change and boundaries

What changed, why, files owned, exclusions and remaining acceptance.

## Verification

- Exact head SHA and base SHA:
- Commands actually run and results:
- Test selection / why new integration or E2E coverage was or was not necessary:
- Live integration versus fixture/replay provenance:
- UI/artifact evidence when relevant:

## Independent review

- [ ] Scope and original OpenSpec failure cases checked.
- [ ] Appropriate tests independently rerun; no unexplained skips/weakened assertions.
- [ ] Sandbox and credential boundaries retained.
- [ ] Current head/base still match evidence.
- [ ] No phase-2 work or unapproved service/data actions.

Merged is not human acceptance. The user owns integration/QA. Automation and automatic merging remain off during setup.
