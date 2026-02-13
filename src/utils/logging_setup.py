
import logging
import sys

_CONFIGURED = False

def setup_logging(level=logging.INFO):
    """
    Configure logging idempotently.
    Safe to call multiple times.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    if root.handlers:
        _CONFIGURED = True
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout
    )
    _CONFIGURED = True
