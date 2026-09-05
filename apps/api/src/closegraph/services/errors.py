class DomainError(ValueError):
    """A fail-closed domain denial; safe to map to an API error."""

class Conflict(DomainError):
    """Optimistic concurrency or immutable identity conflict."""

class AccessDenied(DomainError):
    """Deliberately does not disclose existence outside the resolved scope."""
