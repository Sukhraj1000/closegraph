## Purpose

Turn supported reporting sources into contextual, source-linked facts without losing original evidence or disguising uncertain interpretations as verified data.

## ADDED Requirements

### Requirement: Immutable scoped source receipts
The system SHALL preserve original bytes, content hash, source version, receipt actor/time and tenant/fund/pack scope before processing. Duplicate transport requests MUST NOT create duplicate processing effects; distinct legitimate source receipts MUST remain distinguishable.

#### Scenario: Repeated upload request
- **WHEN** the same authorised upload request is retried with the same idempotency key and bytes
- **THEN** the existing receipt is returned without a second processing effect.

#### Scenario: Conflicting idempotency key
- **WHEN** an upload retries an existing scoped idempotency key with different bytes or source identity
- **THEN** the system rejects the conflict rather than returning the previous receipt as if it represented the new input.

#### Scenario: Source revision
- **WHEN** an authorised user submits revised bytes for an existing source
- **THEN** a new version is created and the original bytes and receipt remain available under their existing permissions.

### Requirement: Bounded extraction capabilities
The system SHALL declare supported formats, layouts, parser settings and evidence quality. Unsupported, unreadable, encrypted or resource-limit-exceeding files MUST be visibly blocked rather than silently converted into guessed values.

#### Scenario: Supported tabular source
- **WHEN** a CSV or XLSX file matches its declared layout and passes safety limits
- **THEN** the system extracts actual records with source coordinates and preserves rejected or excluded records with reasons.

#### Scenario: Unsupported layout
- **WHEN** a source's required table context cannot be established
- **THEN** processing reports the unsupported scope and prevents that scope from becoming ready for release.

### Requirement: Contextual canonical facts
The system SHALL retain raw text/value, normalised decimal value, metric identity, entity, period or as-of date, currency, original unit/scale, interpretation status and source version for each material financial fact. Identifiers MUST remain strings. Missing, zero, not-applicable, conflicting and ambiguous values MUST be distinct.

#### Scenario: Scaled amount
- **WHEN** a supported source displays an amount under a millions-unit heading
- **THEN** the canonical amount records the explicit scale and transformation while retaining the displayed number and supporting heading evidence.

#### Scenario: Unresolved period or currency
- **WHEN** a material value has digits but its required period or currency cannot be established
- **THEN** the context remains unresolved and the fact cannot be treated as a verified comparison operand.

### Requirement: Source and parser provenance
The system SHALL link a fact to supporting page/bounding-box or sheet/cell evidence with coordinate conventions, source text and context. It SHALL record parser identity/version/settings, response/run identity and actually available confidence observations, including their type and provenance.

#### Scenario: PDF citation
- **WHEN** a PDF parser supplies a citation for a material fact
- **THEN** the UI can resolve the original document version and original page, highlight the region and show the context supporting the claimed value.

#### Scenario: Missing confidence
- **WHEN** a native parser provides no calibrated confidence estimate
- **THEN** confidence is marked not-applicable or unavailable with its reason, never fabricated as a percentage.

### Requirement: Completeness and formula limitations
The system SHALL assess supported-scope coverage using declared boundaries and source anchors rather than the parser's returned-row count alone. Formula text and cached results MUST remain distinguishable from executed calculations; an unevaluated or stale cache MUST NOT satisfy a required financial check.

#### Scenario: Missing source row
- **WHEN** extracted records omit a row required by an independent source count or total
- **THEN** coverage fails or remains unknown with the discrepancy recorded, even if the retained rows are internally consistent.

#### Scenario: Formula without a current result
- **WHEN** a required workbook value has a formula but no established current evaluated result
- **THEN** the system preserves the formula/cache evidence and blocks dependent release until a supported computation or authoritative source resolves it.

### Requirement: External processor authorisation and honest availability
The system MUST require approved data scope and configured credentials before external processing. Provider failures MUST remain explicit; captured responses and synthetic observations MUST be labelled and MUST NOT substitute silently for a live provider.

#### Scenario: External processing disabled
- **WHEN** a PDF is submitted without permission or credentials for the configured external parser
- **THEN** no document is sent externally and the UI reports the unavailable capability rather than inventing extracted facts.

#### Scenario: Explicit replay mode
- **WHEN** an authorised test deliberately loads a captured parser response
- **THEN** provenance and the UI identify replay mode, and the run is not counted as live parser verification.
