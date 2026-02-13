"""
CI-only TypeDB initialization script.

Properties:
- No src.config import (env vars only)
- No mock mode (hard fail on any error)
- Driver-based readiness loop (no sleep)
- Creates DB if missing, loads schema, commits
- Exits non-zero on failure

Usage (CI):
    TYPEDB_HOST=localhost TYPEDB_PORT=1729 TYPEDB_DATABASE=scientific_knowledge \
        python scripts/init_ci_db.py
"""

import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config from env only — no src.config
# ---------------------------------------------------------------------------

HOST = os.environ.get("TYPEDB_HOST", "localhost")
PORT = os.environ.get("TYPEDB_PORT", "1729")
DATABASE = os.environ.get("TYPEDB_DATABASE", "scientific_knowledge")
ADDRESS = f"{HOST}:{PORT}"

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "src" / "schema" / "scientific_knowledge.tql"

MAX_RETRIES = 30
RETRY_DELAY = 2  # seconds


def main():
    # ------------------------------------------------------------------
    # 1. Import driver — hard fail if missing
    # ------------------------------------------------------------------
    try:
        from typedb.driver import TypeDB
    except ImportError as e:
        print(f"FATAL: TypeDB driver not installed: {e}", file=sys.stderr)
        sys.exit(1)

    # Enums moved around between driver builds; support both layouts.
    try:
        from typedb.driver import SessionType, TransactionType
    except ImportError:
        try:
            from typedb.api.connection.session import SessionType  # type: ignore
            from typedb.api.connection.transaction import TransactionType  # type: ignore
        except ImportError as e:
            print(f"FATAL: Cannot import SessionType/TransactionType: {e}", file=sys.stderr)
            sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Readiness loop — driver-based, no sleep
    # ------------------------------------------------------------------
    driver = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver = TypeDB.core_driver(ADDRESS)
            # Quick connection test: list databases
            _ = driver.databases.all()
            print(f"TypeDB ready at {ADDRESS} (attempt {attempt})")
            break
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(
                    f"FATAL: TypeDB not reachable at {ADDRESS} after "
                    f"{MAX_RETRIES} attempts: {e}",
                    file=sys.stderr,
                )
                if driver:
                    driver.close()
                sys.exit(1)
            print(f"Waiting for TypeDB ({attempt}/{MAX_RETRIES}): {e}")
            if driver:
                driver.close()
            time.sleep(RETRY_DELAY)

    assert driver is not None  # unreachable, but satisfies type checker

    # ------------------------------------------------------------------
    # 3. Create database if missing
    # ------------------------------------------------------------------
    try:
        if not driver.databases.contains(DATABASE):
            driver.databases.create(DATABASE)
            print(f"Created database: {DATABASE}")
        else:
            print(f"Database already exists: {DATABASE}")
    except Exception as e:
        print(f"FATAL: Could not create database '{DATABASE}': {e}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Load schema — fail hard on any error
    # ------------------------------------------------------------------
    if not SCHEMA_PATH.exists():
        print(f"FATAL: Schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)

    schema_content = SCHEMA_PATH.read_text(encoding="utf-8")
    print(f"Loading schema from {SCHEMA_PATH.name} ({len(schema_content)} bytes)")

    try:
        with driver.session(DATABASE, SessionType.SCHEMA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.define(schema_content)
                tx.commit()
        print("Schema loaded successfully")
    except Exception as e:
        print(f"FATAL: Schema load failed: {e}", file=sys.stderr)
        sys.exit(1)

    driver.close()
    print(f"CI database '{DATABASE}' initialized at {ADDRESS}")


if __name__ == "__main__":
    main()
