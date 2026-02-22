#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def repo_head_ordinal(migrations_dir: str) -> int:
    p = Path(migrations_dir)
    if not p.exists():
        raise FileNotFoundError(f"migrations_dir not found: {migrations_dir}")
    ords = []
    for f in p.glob("*.tql"):
        m = re.match(r"^(\d+)_", f.name)
        if m:
            ords.append(int(m.group(1)))
    return max(ords) if ords else 0


def db_current_ordinal(driver, db: str) -> int:
    from typedb.driver import TransactionType

    q = "match $v isa schema_version, has ordinal $o; select $o;"
    with driver.transaction(db, TransactionType.READ) as tx:
        ans = tx.query(q).resolve()
        ords = []
        for row in ans.as_concept_rows():
            c = row.get("o")
            if c and c.is_attribute():
                ords.append(int(c.as_attribute().get_value()))
        return max(ords) if ords else 0


def connect(address: str, username: str, password: str, tls: bool, ca_path: str | None):
    from typedb.driver import Credentials, DriverOptions, TypeDB

    creds = Credentials(username, password)
    opts = DriverOptions(is_tls_enabled=tls, tls_root_ca_path=ca_path)
    return TypeDB.driver(address, creds, opts)


def main() -> int:
    migrations_dir = os.getenv("TYPEDB_MIGRATIONS_DIR", "src/schema/migrations")
    address = os.getenv("TYPEDB_ADDRESS")
    db = os.getenv("TYPEDB_DATABASE")
    user = os.getenv("TYPEDB_USERNAME")
    pw = os.getenv("TYPEDB_PASSWORD")
    tls = env_bool("TYPEDB_TLS", "false")
    ca = os.getenv("TYPEDB_ROOT_CA_PATH") or None

    if not address or not db or not user or not pw:
        print("[schema_health] SKIP: missing TypeDB env vars")
        return 0

    try:
        repo_ordinal = repo_head_ordinal(migrations_dir)
        print(f"[schema_health] Repo head ordinal: {repo_ordinal}")

        driver = connect(address, user, pw, tls, ca)
        try:
            db_ordinal = db_current_ordinal(driver, db)
            print(f"[schema_health] DB current ordinal: {db_ordinal}")
        finally:
            driver.close()

        if db_ordinal != repo_ordinal:
            print(f"[schema_health] FAIL: drift detected repo={repo_ordinal} db={db_ordinal}")
            return 1

        print("[schema_health] PASS: parity OK")
        return 0
    except Exception as e:
        print(f"[schema_health] ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
