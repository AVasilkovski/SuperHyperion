"""
WriteCap — Phase 16.3

Opaque capability token that gates write access to TypeDB.
Only the OntologySteward may mint this token.
"""


class WriteCap:
    """Opaque write-capability token. Cannot be constructed directly."""

    _SENTINEL = object()

    def __init__(self, _key=None):
        if _key is not self._SENTINEL:
            raise RuntimeError("WriteCap must not be constructed directly")

    @classmethod
    def _mint(cls) -> "WriteCap":
        """Internal: mint a new WriteCap (only for authorized agents)."""
        return cls(_key=cls._SENTINEL)
