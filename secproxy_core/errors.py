class ServiceError(RuntimeError):
    """Base error for framework-neutral service operations."""

class ConflictError(ServiceError):
    """Requested operation conflicts with current persisted/runtime state."""
