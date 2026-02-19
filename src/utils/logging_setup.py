
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
        # If someone already set up handlers, we don't want to call basicConfig
        # which would raise the "already initialized" warning if called multiple times
        # in some environments, though basicConfig(force=True) is 3.8+
        _CONFIGURED = True
        return

    try:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stdout
        )
    except ValueError:
        # Handled by _CONFIGURED check above, but for extra safety
        pass
    _CONFIGURED = True
