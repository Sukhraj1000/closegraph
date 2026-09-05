## Purpose

Compute reproducible financial checks and carry an authorised correction through its dependent outputs without repeating unrelated review or concealing failed results.

## Requirements

### Requirement: Explicit versioned financial checks
The system SHALL execute required structural/data checks and financial rules against pinned fact, mapping, rule and policy versions. A result SHALL identify its operands, scope, expected relationship, computed difference, tolerance and PASS, FAIL, UNKNOWN or justified NOT_APPLICABLE outcome. Imported pass flags MUST NOT be authoritative.

#### Scenario: High-confidence inconsistent balance sheet
- **WHEN** the supported balance-sheet equation fails for aligned entity, period and currency operands
- **THEN** the check records the actual operands and discrepancy, links every contributing fact, and identifies an inconsistent relationship without asserting an unsupported culprit.

#### Scenario: Unknown required check
- **WHEN** a required reconciliation lacks an operand or applicable authorised rule
- **THEN** its outcome is UNKNOWN and cannot be treated as PASS or silently omitted.

#### Scenario: Actual data validation
- **WHEN** column types are valid but rows violate a required constraint
- **THEN** data-level validation detects the violation rather than reporting success from a schema-only check.

### Requirement: Explicit mappings and supported computations
The system SHALL apply only approved scoped mappings and supported deterministic financial computations. It MUST preserve mapping/rule provenance and rounding policy, and MUST NOT infer arbitrary legal treatment or use an unconstrained model-generated value as the calculation authority.

#### Scenario: Authorised fee treatment
- **WHEN** the configured workflow has source-supported approved fee inputs and a versioned treatment rule
- **THEN** the tool computes the supported result using decimal arithmetic and records that exact rule and input lineage.

#### Scenario: Ambiguous mapping
- **WHEN** a source label or transaction can map to multiple financial concepts under the available evidence
- **THEN** the alternatives remain unresolved until a scoped authorised decision is recorded.

### Requirement: Versioned source-backed corrections
The system SHALL create a new fact or treatment version for each authorised correction, recording actor, reason, evidence and superseded version. It MUST retain original parser observations and original check results. A reviewer action alone MUST NOT change FAIL to PASS.

#### Scenario: Correct an extracted value
- **WHEN** an authorised preparer corrects a value with supporting evidence and a reason
- **THEN** a new version is created, dependent checks become pending or stale, and the old observation remains traceable.

#### Scenario: Attempt to approve an unresolved failed check
- **WHEN** a reviewer attempts to approve a scope whose required check still fails
- **THEN** the application rejects approval/release eligibility and preserves the failed diagnostic.

### Requirement: Evidence-backed impact propagation
The system SHALL compute change impact from scoped versioned dependencies, including supported rule and mapping changes. It MUST reopen affected checks and reviews; it MUST NOT claim an output is unaffected when relevant dependency coverage is unknown or cyclic beyond supported execution.

#### Scenario: Scoped correction
- **WHEN** a corrected fee affects the investor statement but a separate output has established independent dependencies
- **THEN** the statement's dependent work is reopened and the independent output retains its own valid snapshot evidence.

#### Scenario: Unknown dependency
- **WHEN** the system cannot establish whether a changed fact feeds an output
- **THEN** the potentially affected scope is marked unverifiable and cannot retain a current-ready claim.

### Requirement: Recoverable snapshot execution
The system SHALL bind processing to immutable input/configuration identities, persist outcomes and make business effects idempotent under retries. Late results MUST NOT overwrite newer pack state. Pending human review MUST NOT require a continuously running computation.

#### Scenario: Process interruption and replay
- **WHEN** execution stops after writing a stage result and the same processing identity is retried
- **THEN** the result is safely reused or recomputed without duplicate corrections, approvals or publications.

#### Scenario: Older run finishes last
- **WHEN** a run for an older pack revision completes after a newer revision exists
- **THEN** its result remains historical and does not replace the newer revision's current pointer.

### Requirement: Failed checks remain inspectable
The system SHALL persist financial failures and route them to the reviewer workspace even when release is blocked. Infrastructure errors SHALL remain distinct from financial check failures.

#### Scenario: Reconciliation failure
- **WHEN** extraction succeeds but a required financial check fails
- **THEN** the facts, discrepancy and reasons appear in review while publication remains blocked.

#### Scenario: Parser service outage
- **WHEN** the parser cannot complete because the service is unavailable
- **THEN** processing reports an infrastructure/provider failure without inventing a financial pass or failure.
