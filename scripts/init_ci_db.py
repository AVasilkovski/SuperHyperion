#!/usr/bin/env python3
"""
Initialize TypeDB schema for CI.
Uses TypeDB 3.x transaction-only API.
"""

import os
import sys
import time
from pathlib import Path

# Configuration from environment
HOST = os.environ.get("TYPEDB_HOST", "localhost")
PORT = os.environ.get("TYPEDB_PORT", "1729")
DATABASE = os.environ.get("TYPEDB_DATABASE", "scientific_knowledge")
ADDRESS = f"{HOST}:{PORT}"

# TypeDB Core docker defaults
USERNAME = os.environ.get("TYPEDB_USERNAME", "admin")
PASSWORD = os.environ.get("TYPEDB_PASSWORD", "password")

# Schema path (relative to repo root)
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "src" / "schema" / "scientific_knowledge.tql"

MAX_RETRIES = 30
RETRY_DELAY = 2

def main():
    try:
        from typedb.driver import Credentials, DriverOptions, TransactionType, TypeDB
    except Exception as e:
        print(f"FATAL: TypeDB driver API not importable via typedb.driver: {e}", file=sys.stderr)
        sys.exit(1)

    if not SCHEMA_PATH.exists():
        print(f"FATAL: Schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials(USERNAME, PASSWORD)
    opts = DriverOptions(is_tls_enabled=False, tls_root_ca_path=None)

    driver = None
    last_err = None

    # Readiness loop
    print(f"Connecting to TypeDB at {ADDRESS}...")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver = TypeDB.driver(ADDRESS, creds, opts)
            # Quick connection test: list databases
            _ = driver.databases.all()
            print(f"TypeDB ready at {ADDRESS} (attempt {attempt})")
            break
        except Exception as e:
            last_err = e
            print(f"Waiting for TypeDB ({attempt}/{MAX_RETRIES}): {e}")
            if driver:
                try:
                    driver.close()
                except Exception:
                    pass
                driver = None
            time.sleep(RETRY_DELAY)

    if not driver:
        print(f"FATAL: TypeDB not reachable at {ADDRESS} after {MAX_RETRIES} attempts: {last_err}", file=sys.stderr)
        sys.exit(1)

    try:
        # Create DB if missing
        if not driver.databases.contains(DATABASE):
            driver.databases.create(DATABASE)
            print(f"Created database: {DATABASE}")
        else:
            print(f"Database already exists: {DATABASE}")

        schema_content = SCHEMA_PATH.read_text(encoding="utf-8")
        print(f"Loading schema from {SCHEMA_PATH.name} ({len(schema_content)} bytes)")

        # Load schema via SCHEMA transaction
        with driver.transaction(DATABASE, TransactionType.SCHEMA) as tx:
            # tx.query(...) in 3.x returns a ReqHelper which must be resolved
            tx.query(schema_content).resolve()
            tx.commit()

        print("Schema loaded successfully")
        print(f"CI database '{DATABASE}' initialized at {ADDRESS}")

    except Exception as e:
        print(f"FATAL: Schema init failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            driver.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
