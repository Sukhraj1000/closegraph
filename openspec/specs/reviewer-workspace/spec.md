## Purpose

Give administrators and independent reviewers a usable source-to-correction-to-output workspace that reduces reconstruction work without hiding uncertainty or requiring them to operate a data platform.

## Requirements

### Requirement: Separate business state and processing state
The workspace SHALL show execution status, check outcomes, review routing, approval and version currency separately. It SHALL present a next action and useful diagnostic when work fails or is blocked. Technical orchestration success MUST NOT appear as financial approval.

#### Scenario: Pipeline succeeds with inconsistent data
- **WHEN** all processing functions complete but a financial rule fails
- **THEN** the workspace shows completed processing and BLOCKED review with the discrepancy, not an approved or trusted-data badge.

#### Scenario: Pending human review
- **WHEN** processing has produced a reviewable snapshot
- **THEN** the reviewer can act through the application without opening the orchestration UI or waiting for a background job to remain alive.

### Requirement: Evidence-first review and navigation
The workspace SHALL show source and extracted/normalised values side by side, with original and proposed versions, rule results and routing reasons. Ready items SHALL remain inspectable and receive audit sampling; the interface MUST NOT hide all unflagged values or claim only flagged values can be wrong.

#### Scenario: Trace and correct a value
- **WHEN** a reviewer opens a flagged amount
- **THEN** they can inspect its original source location, context, parser observations and failed relationships, and an authorised preparer can record an evidenced correction with a reason.

#### Scenario: Inspect a green item
- **WHEN** a user selects a READY_FOR_QUICK_REVIEW item
- **THEN** the same source and policy evidence is available and no guarantee of correctness is asserted.

### Requirement: Complete correction-loop interaction
The workspace SHALL support original pack ingestion, discrepancy review, authorised correction, affected-result recomputation, renewed independent approval and exact revised output download. It SHALL show unresolved missing-evidence blockers but MUST NOT require phase-2 request/deadline automation to complete this loop.

#### Scenario: Failed repair followed by successful repair
- **WHEN** a first correction leaves a required relationship failing and a later evidenced correction resolves it
- **THEN** the first attempt remains visible, only the later checked snapshot becomes eligible for independent approval, and the downloaded pack reflects that version.

### Requirement: Observed review-work measurement
The system SHALL record review actions, correction iterations, reopened output scope and elapsed processing/review events with their case context. Reports MUST distinguish synthetic demos, automated tests and customer pilots, and MUST NOT infer customer savings from fabricated baselines.

#### Scenario: Demonstration report
- **WHEN** a synthetic correction journey completes
- **THEN** its report shows observed actions and test provenance without claiming a measured reduction in real customer review rounds.
