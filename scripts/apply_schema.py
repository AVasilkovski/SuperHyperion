#!/usr/bin/env python3
import argparse
import os
import sys
import time
from pathlib import Path

<<<<<<< HEAD
from typedb.driver import TypeDB, Credentials, DriverOptions, SessionType, TransactionType
=======
from typedb.driver import Credentials, DriverOptions, TransactionType, TypeDB
>>>>>>> origin/main


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def connect_with_retries(
    address: str,
    username: str,
    password: str,
    tls: bool,
    ca_path: str | None,
    retries: int = 30,
    sleep_s: float = 2.0,
):
    creds = Credentials(username, password)
    opts = DriverOptions(is_tls_enabled=tls, tls_root_ca_path=ca_path)

    last_err = None
    for i in range(1, retries + 1):
        try:
            driver = TypeDB.driver(address, creds, opts)
            # Force a real roundtrip
            _ = [d.name for d in driver.databases.all()]
            return driver
        except Exception as e:
            last_err = e
            print(f"[apply_schema] waiting for TypeDB ({i}/{retries})... {e}")
            time.sleep(sleep_s)
    raise RuntimeError(f"TypeDB not ready after {retries} attempts. Last error: {last_err}")


def ensure_database(driver, db: str):
    existing = {d.name for d in driver.databases.all()}
    if db not in existing:
        driver.databases.create(db)
        print(f"[apply_schema] created database: {db}")
    else:
        print(f"[apply_schema] database exists: {db}")


def apply_schema(driver, db: str, schema_path: Path):
    schema = schema_path.read_text(encoding="utf-8")
<<<<<<< HEAD
    with driver.session(db, SessionType.SCHEMA) as session:
        with session.transaction(TransactionType.WRITE) as tx:
            tx.query().define(schema)
            tx.commit()
=======
    with driver.transaction(db, TransactionType.SCHEMA) as tx:
        tx.query(schema).resolve()
        tx.commit()
>>>>>>> origin/main
    print(f"[apply_schema] schema applied: {schema_path}")


def main():
    p = argparse.ArgumentParser(description="Apply TypeDB schema (local Core or Cloud TLS).")
    p.add_argument("--schema", default=os.getenv("TYPEDB_SCHEMA", "src/schema/scientific_knowledge.tql"))
    p.add_argument("--database", default=os.getenv("TYPEDB_DATABASE", "scientific_knowledge"))
    p.add_argument("--host", default=os.getenv("TYPEDB_HOST", "localhost"))
    p.add_argument("--port", default=os.getenv("TYPEDB_PORT", "1729"))
    p.add_argument("--username", default=os.getenv("TYPEDB_USERNAME", "admin"))
    p.add_argument("--password", default=os.getenv("TYPEDB_PASSWORD", "password"))
    args = p.parse_args()

    tls = env_bool("TYPEDB_TLS", "false")
    ca_path = os.getenv("TYPEDB_ROOT_CA_PATH") or None

    schema_path = Path(args.schema)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    address = f"{args.host}:{args.port}"
    print(f"[apply_schema] connecting to {address} tls={tls} ca={ca_path}")

    driver = connect_with_retries(address, args.username, args.password, tls, ca_path)
    try:
        ensure_database(driver, args.database)
        apply_schema(driver, args.database, schema_path)
    finally:
        driver.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[apply_schema] ERROR: {e}")
        sys.exit(1)
