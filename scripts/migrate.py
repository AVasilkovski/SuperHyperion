#!/usr/bin/env python3
import argparse
import os
import sys
import time
from pathlib import Path


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
    from typedb.driver import Credentials, DriverOptions, TypeDB
    creds = Credentials(username, password)
    opts = DriverOptions(is_tls_enabled=tls, tls_root_ca_path=ca_path)

    last_err = None
    for i in range(1, retries + 1):
        try:
            driver = TypeDB.driver(address, creds, opts)
            _ = [d.name for d in driver.databases.all()]
            return driver
        except Exception as e:
            last_err = e
            print(f"[migrate] waiting for TypeDB ({i}/{retries})... {e}")
            time.sleep(sleep_s)
    raise RuntimeError(f"TypeDB not ready after {retries} attempts. Last error: {last_err}")

def get_current_schema_version(driver, db: str) -> int:
    from typedb.driver import TransactionType
    query = "match $v isa schema_version, has ordinal $o; select $o;"
    try:
        with driver.transaction(db, TransactionType.READ) as tx:
            results = list(tx.query(query).resolve())
            if not results:
                return 0
            # Get the max ordinal
            ordinals = [r.get("o").as_attribute().get_value() for r in results]
            return max(ordinals) if ordinals else 0
    except Exception as e:
        # Before the schema is applied, the entity might not exist resulting in a TypeDB exception.
        print(f"[migrate] schema_version query failed (likely no schema yet): {e}")
        return 0

def get_migrations(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.is_dir():
        return []
    
    files = list(migrations_dir.glob("*.tql"))
    # Sort files by the numeric prefix
    def _extract_ordinal(p: Path) -> int:
        name = p.name
        parts = name.split("_")
        if parts and parts[0].isdigit():
            return int(parts[0])
        return -1
    
    valid_files = [f for f in files if _extract_ordinal(f) >= 0]
    return sorted(valid_files, key=_extract_ordinal)

def apply_migration(driver, db: str, migration_file: Path, next_ordinal: int, dry_run: bool):
    import datetime

    from typedb.driver import TransactionType
    
    print(f"[migrate] Applying migration: {migration_file.name} (Ordinal: {next_ordinal})")
    
    if dry_run:
        print(f"[migrate] DRY-RUN: Would execute {migration_file.name}")
        return
        
    schema = migration_file.read_text(encoding="utf-8")
    git_commit = os.getenv("GITHUB_SHA", "unknown")
    applied_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    
    # Needs to be a split transaction for schema vs data in older TypeDBs sometimes, 
    # but in 3.x schema tx can handle rule additions and schema.
    # To be safe and compliant, we do schema first, then data transaction for the version record.
    
    with driver.transaction(db, TransactionType.SCHEMA) as tx:
        tx.query(schema).resolve()
        tx.commit()
        
    # Then insert the version record
    # Requires schema_version to exist, which it might not if it's the 001 migration.
    # The 001 migration *must* include the schema_version definition.
    version_query = f"""
    insert $v isa schema_version, 
      has ordinal {next_ordinal},
      has git-commit "{git_commit}",
      has applied-at {applied_at};
    """
    
    with driver.transaction(db, TransactionType.WRITE) as tx:
        tx.query(version_query).resolve()
        tx.commit()

def ensure_database(driver, db: str):
    existing = {d.name for d in driver.databases.all()}
    if db not in existing:
        driver.databases.create(db)
        print(f"[migrate] created database: {db}")
    else:
        print(f"[migrate] database exists: {db}")

def main():
    p = argparse.ArgumentParser(description="Deterministic linear schema migrations for TypeDB.")
    p.add_argument("--migrations-dir", default="schema/migrations", help="Directory containing NNN_*.tql files")
    p.add_argument("--database", default=os.getenv("TYPEDB_DATABASE", "scientific_knowledge"))
    p.add_argument("--address", default=os.getenv("TYPEDB_ADDRESS"))
    p.add_argument("--host", default=os.getenv("TYPEDB_HOST", "localhost"))
    p.add_argument("--port", default=os.getenv("TYPEDB_PORT", "1729"))
    p.add_argument("--username", default=os.getenv("TYPEDB_USERNAME", "admin"))
    p.add_argument("--password", default=os.getenv("TYPEDB_PASSWORD", "password"))
    p.add_argument("--recreate", action="store_true", help="Delete and recreate the database before applying.")
    p.add_argument("--dry-run", action="store_true", help="Print planned migration actions without executing.")
    p.add_argument("--target", type=int, default=None, help="Apply migrations up to this ordinal.")
    args = p.parse_args()

    print(f"[migrate] argv: {sys.argv[1:]}")

    tls = env_bool("TYPEDB_TLS", "false")
    ca_path = os.getenv("TYPEDB_ROOT_CA_PATH") or None

    address = args.address if args.address else f"{args.host}:{args.port}"
    mig_dir = Path(args.migrations_dir)
    # Default to standard project structure if run from root
    if not mig_dir.exists():
        mig_dir = Path("src/schema/migrations")
        if not mig_dir.exists():
             print(f"[migrate] WARNING: Migrations directory not found: {args.migrations_dir}")
             return 0

    all_migrations = get_migrations(mig_dir)
    print(f"[migrate] Found {len(all_migrations)} migrations in {mig_dir}")

    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    if is_ci and (not address or address == ":"):
        print("[migrate] SKIP: Skipping Cloud deployment in CI (secrets missing for branch/PR)")
        return 0

    print(f"[migrate] connecting to {address} tls={tls} ca={ca_path}")

    driver = connect_with_retries(address, args.username, args.password, tls, ca_path)
    try:
        if args.recreate:
            if driver.databases.contains(args.database):
                driver.databases.get(args.database).delete()
                print(f"[migrate] database deleted: {args.database}")

        ensure_database(driver, args.database)

        current_ordinal = get_current_schema_version(driver, args.database)
        print(f"[migrate] Current schema version ordinal: {current_ordinal}")
        
        pending_migrations = []
        for mig in all_migrations:
            parts = mig.name.split("_")
            ordinal = int(parts[0])
            if ordinal > current_ordinal:
                if args.target is not None and ordinal > args.target:
                    continue
                pending_migrations.append((ordinal, mig))
                
        if not pending_migrations:
            print("[migrate] No pending migrations to apply.")
            return 0
            
        print(f"[migrate] Planning to apply {len(pending_migrations)} migrations.")
        for ordinal, path in pending_migrations:
            apply_migration(driver, args.database, path, ordinal, args.dry_run)
            
        print("[migrate] Migration completed cleanly.")
            
    finally:
        driver.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())
