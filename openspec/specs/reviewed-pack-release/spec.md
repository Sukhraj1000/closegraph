## Purpose

Make review decisions and released reporting packs traceable to exact supported snapshots, while enforcing scoped access and preventing stale or failed work from being published.

## Requirements

### Requirement: Independent exact-snapshot approval
The system SHALL require an authorised reviewer independent of the preparer/corrector to approve a specified output and dependency snapshot. Approval SHALL record actor, time, scope, decision and reason separately from extraction and validation. NEEDS_REVIEW signals SHALL require explicit evidence-backed adjudication; hard blockers MUST NOT be waived in the MVP.

#### Scenario: Preparer attempts self-approval
- **WHEN** the actor who prepared or corrected a release scope attempts its final approval
- **THEN** approval is denied and no approved snapshot is created.

#### Scenario: Reviewer resolves a soft signal
- **WHEN** an independent reviewer inspects supporting evidence, resolves a parser disagreement and approves a snapshot whose required checks pass
- **THEN** the decision records the resolution without erasing the disagreement observations or changing past check outcomes.

#### Scenario: Reviewer selects a different value
- **WHEN** resolving a parser disagreement would change a material value, context or treatment in the candidate snapshot
- **THEN** the system creates a correction/new snapshot and reruns dependent checks before that revised snapshot can receive final independent approval; approval of the previous candidate does not carry forward.

### Requirement: Backend release eligibility
The system MUST compute publication eligibility from trusted stored policy, current snapshot, required passing checks, resolved review issues, valid independent approval and exact output integrity. Client-supplied role labels, pass flags, confidence scores or job success MUST NOT grant eligibility.

#### Scenario: Forged pass request
- **WHEN** a client submits a release request containing fabricated passed-check or approval fields
- **THEN** those fields cannot bypass the backend gate and unauthorised release is denied.

#### Scenario: Missing bytes or required evidence
- **WHEN** an approved snapshot references missing/corrupt output bytes or incomplete required evidence
- **THEN** publication is denied and the unresolved state is visible.

### Requirement: Version freshness and race safety
The system SHALL reject approval/publication for stale input, rule, mapping, policy or output versions. Publication MUST atomically check the current authoritative snapshot before registering the released version. Unknown external freshness MUST remain visible.

#### Scenario: Change between approval and release
- **WHEN** a relevant source, mapping or policy changes after approval but before publication commits
- **THEN** the old approval cannot release the new current pack and affected review must be renewed.

#### Scenario: Unobserved external state
- **WHEN** an external source cannot be refreshed under its declared freshness policy
- **THEN** the system reports the last observation and does not imply knowledge of unobserved changes.

### Requirement: Idempotent publication and historical evidence
The system SHALL register at most one business publication for an identical authorised release request/snapshot, preserve historic decisions and identify stale or superseded releases. Downloaded copies MUST include version/as-of context or an accompanying manifest; the system MUST NOT imply it can recall external copies.

#### Scenario: Duplicate release request
- **WHEN** an identical authorised release request is retried
- **THEN** the existing publication is returned rather than a duplicate release effect.

#### Scenario: Inspect superseded output
- **WHEN** an authorised user opens an older released pack after a correction
- **THEN** its original bytes and decision history remain accessible with a clear historical/stale/superseded label.

### Requirement: Permissioned review and evidence access
The system MUST enforce server-resolved identity and tenant/fund/pack/document scope on every read and mutation, including files, graph edges, counts, diagnostics and downloads. Untrusted documents MUST NOT trigger privileged actions.

#### Scenario: Cross-fund access
- **WHEN** an authenticated actor requests another fund's pack, citation, count or download without permission
- **THEN** access is denied without leaking the protected content or existence through the response.

#### Scenario: Document instruction masquerades as approval
- **WHEN** uploaded content asks the system to mark all figures approved or send a document externally
- **THEN** it is retained only as source content and cannot change policy, authority or external-processing permission.

### Requirement: Supported template-preserving output
The system SHALL produce a corrected pack in one explicitly supported template, plus a separate source/check/review manifest. Only declared mapped output fields may change; unsupported template features MUST block generation rather than silently disappear. Original artifacts MUST remain immutable.

#### Scenario: Corrected output download
- **WHEN** a supported correction has passed checks and independent approval
- **THEN** the released pack contains the recomputed mapped values, retains the supported template layout and includes a manifest identifying the exact sources, rules, checks and approval.

#### Scenario: Unsupported output feature
- **WHEN** generating a pack would require an unsupported macro, formula evaluation or template structure
- **THEN** the system reports the unsupported feature instead of publishing a degraded pack as equivalent.
