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
    query = "match $v isa schema_version, has ordinal $o; get $o;"
    try:
        with driver.transaction(db, TransactionType.READ) as tx:
            results = tx.query(query).resolve()
            ordinals = []
            for r in results.as_concept_rows():
                o = r.get("o")
                if o and o.is_attribute():
                    ordinals.append(int(o.as_attribute().get_value()))
            return max(ordinals) if ordinals else 0
    except Exception as e:
        # Catch ConceptError or missing schema_version gracefully
        print(f"[migrate] schema_version query failed (returning 0): {e}")
        return 0

def get_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    if not migrations_dir.is_dir():
        return []
    
    files = list(migrations_dir.glob("*.tql"))
    valid_files = []
    seen_ordinals = set()
    
    allow_gaps = env_bool("MIGRATIONS_ALLOW_GAPS", "false")
    
    for f in files:
        name = f.name
        parts = name.split("_")
        if not parts or not parts[0].isdigit():
            raise ValueError(f"Invalid migration filename format: {name}. Must be NNN_name.tql")
        
        ordinal = int(parts[0])
        if ordinal < 1:
            raise ValueError(f"Invalid migration ordinal: {ordinal} in {name}. Must be >= 1")
            
        if ordinal in seen_ordinals:
            raise ValueError(f"Duplicate migration ordinal detected: {ordinal}")
            
        seen_ordinals.add(ordinal)
        valid_files.append((ordinal, f))
        
    valid_files.sort(key=lambda x: x[0])
    
    # Gap detection
    if valid_files and not allow_gaps:
        expected = 1
        for ord_val, _ in valid_files:
            if ord_val != expected:
                raise ValueError(f"Migration gap detected: expected {expected}, got {ord_val}")
            expected += 1
            
    # Check 001_* contains schema_version definitions
    if valid_files:
        first_ord, first_path = valid_files[0]
        if first_ord == 1:
            content = first_path.read_text(encoding="utf-8")
            if "schema_version" not in content or "ordinal" not in content or "git-commit" not in content or "applied-at" not in content:
                raise ValueError(f"Migration 001 must contain 'schema_version' definitions with 'ordinal', 'git-commit', 'applied-at'. Found in {first_path.name}: missing standard keywords.")
    
    return valid_files

def apply_migration(driver, db: str, migration_file: Path, next_ordinal: int, dry_run: bool):
    import datetime
    import hashlib

    from typedb.driver import TransactionType
    
    schema = migration_file.read_text(encoding="utf-8").strip()
    
    # Migration hygiene: must start with define/undefine/redefine
    if not any(schema.lower().startswith(kw) for kw in ["define", "undefine", "redefine"]):
         raise ValueError(f"Migration hygiene violation: {migration_file.name} must start with define/undefine/redefine. Found: {schema[:20]}...")

    file_hash = hashlib.sha256(schema.encode("utf-8")).hexdigest()[:12]
    
    print(f"[migrate] applying {migration_file.name} (sha256: {file_hash})")
    
    if dry_run:
        return
        
    git_commit = os.getenv("GITHUB_SHA", "unknown")
    applied_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    
    try:
        with driver.transaction(db, TransactionType.SCHEMA) as tx:
            tx.query(schema).resolve()
            tx.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to apply SCHEMA transaction for {migration_file.name} (Ordinal: {next_ordinal}): {e}") from e
        
    version_query = f"""
    insert $v isa schema_version, 
      has ordinal {next_ordinal},
      has git-commit "{git_commit}",
      has applied-at {applied_at};
    """
    
    try:
        with driver.transaction(db, TransactionType.WRITE) as tx:
            tx.query(version_query).resolve()
            tx.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to apply WRITE transaction for {migration_file.name} (Ordinal: {next_ordinal}): {e}") from e

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
        for ordinal, mig in all_migrations:
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
