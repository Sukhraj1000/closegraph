## Purpose

Prioritise human verification using explicit evidence/financial gates and parser observations, without representing a model confidence score as financial truth.

## Requirements

### Requirement: Hard-gate routing precedence
The system SHALL route each review scope to BLOCKED, NEEDS_REVIEW or READY_FOR_QUICK_REVIEW using a pinned explainable policy. Required failed/unknown checks, missing material evidence, unresolved material context or unverifiable dependencies MUST produce BLOCKED. Soft risk scores MUST NOT offset these gates.

#### Scenario: Confidence cannot cancel financial failure
- **WHEN** parsers report high confidence and agree but a required reconciliation fails
- **THEN** the scope is BLOCKED and the failed relationship is the leading reason.

#### Scenario: Pending required checks
- **WHEN** a required check has not completed
- **THEN** the scope cannot be READY_FOR_QUICK_REVIEW.

### Requirement: Separate and contextual parser signals
The system SHALL preserve parser confidence and parser agreement as separate observations. Agreement MUST compare entity, metric, period, currency, scale and value under explicit normalisation. NOT_RUN, UNAVAILABLE, NOT_APPLICABLE, AGREE and DISAGREE MUST remain distinguishable; agreement MUST NOT be described as independent proof of truth.

#### Scenario: Same digits with different scale
- **WHEN** two observations contain the same digits but disagree on units or period
- **THEN** they do not count as agreement; resolved-context disagreement requires review, while unresolved required context remains blocked.

#### Scenario: Optional second pass absent
- **WHEN** a second parser was not run
- **THEN** the system records NOT_RUN and uses the applicable single-parser policy without claiming two-parser agreement.

### Requirement: Conservative quick-review eligibility
The system SHALL offer quick review only when required evidence/checks pass and a versioned policy supports the observed signal pattern. Missing or uncalibrated AI confidence MUST NOT silently receive a favourable default. Native structured extraction MAY use an explicitly tested single-parser policy with confidence marked not-applicable.

#### Scenario: Supported native extraction
- **WHEN** native extraction has explicit source coordinates, complete context, passing required checks and a tested applicable single-parser policy
- **THEN** the scope can be READY_FOR_QUICK_REVIEW without an invented confidence percentage or second parser.

#### Scenario: Unevaluated AI threshold
- **WHEN** a probabilistic parser provides a high score but its quick-review policy lacks evaluation evidence for the supported scope
- **THEN** the scope is at least NEEDS_REVIEW rather than automatically ready.

#### Scenario: Parser disagreement without a hard blocker
- **WHEN** required evidence/checks pass but unresolved parser disagreement remains
- **THEN** the scope is NEEDS_REVIEW with both candidate observations visible.

### Requirement: Explainable priority without false certainty
The system SHALL display routing reasons, policy version, check coverage and available parser observations. Within a route it SHALL prioritise by configured materiality and downstream impact; a priority value MUST NOT be labelled a probability of correctness. Quick review MUST still require an authorised human decision.

#### Scenario: User opens a ready item
- **WHEN** a reviewer opens a READY_FOR_QUICK_REVIEW item
- **THEN** evidence, passed checks and policy reasons are visible and the item remains unapproved until an explicit authorised decision.

#### Scenario: Material failed relationship
- **WHEN** a material multi-fact reconciliation fails
- **THEN** the queue groups the relevant facts under the failed relationship rather than presenting an unproven single bad value.

### Requirement: Policy evaluation and correction feedback
The system SHALL version routing policies and record reviewer corrections as labelled evidence without silently changing live policy. Evaluation SHALL include held-out labelled cases, missed/rejected records, contextual errors, correlated parser errors, false-ready outcomes, coverage and reviewer burden. Observed results MUST be labelled with dataset scope and MUST NOT imply universal accuracy.

#### Scenario: Agreeing parsers are both wrong
- **WHEN** a labelled test has agreeing parser outputs with an incorrect financial value or context
- **THEN** the evaluation records the erroneous readiness outcome if one occurs, even when internal reconciliation passes.

#### Scenario: Reviewer corrects a case
- **WHEN** a reviewer resolves an extraction disagreement
- **THEN** the correction and reason are retained for evaluation without automatically modifying thresholds or approving similar future facts.
