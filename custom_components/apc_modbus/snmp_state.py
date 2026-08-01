"""Small SNMP availability predicates shared by retry and routine refresh."""

from typing import Any


def has_usable_metadata(metadata: Any) -> bool:
    """Return whether an SNMP metadata response can enrich an entry."""
    return isinstance(metadata, dict) and any(metadata.values())
