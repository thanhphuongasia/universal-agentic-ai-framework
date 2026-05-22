"""Back-compat shim. Canonical: `ryuu_observability_core.audit`."""
from ryuu_observability_core.audit import (
    AuditConfig, AuditEvent, AuditLogger, verify_chain,
)
__all__ = ["AuditConfig", "AuditEvent", "AuditLogger", "verify_chain"]
