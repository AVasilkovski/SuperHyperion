#!/usr/bin/env python3
import argparse
import glob
import os
import re
import sys
import time
from pathlib import Path

from typedb.driver import Credentials, DriverOptions, TransactionType, TypeDB


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def resolve_schema_files(schema_args: list[str]) -> list[Path]:
    """Resolve schema file arguments (paths and/or globs) deterministically."""
    resolved: list[Path] = []
    for item in schema_args:
        has_glob_chars = any(char in item for char in "*?[")
        if "***" in item:
            raise FileNotFoundError(
                f"Invalid schema glob pattern: {item}. "
                "Use explicit canonical schema path(s) or valid glob syntax (for example: src/schema/**/*.tql)."
            )
        matches = sorted(Path(p) for p in glob.glob(item, recursive=True))
        file_matches = [m for m in matches if m.is_file()]
        if file_matches:
            resolved.extend(file_matches)
            continue

        if has_glob_chars:
            raise FileNotFoundError(
                f"Schema glob matched no files: {item}. "
                "Pass explicit canonical schema path(s), e.g. src/schema/scientific_knowledge.tql"
            )

        path = Path(item)
        if path.is_file():
            resolved.append(path)
            continue

        raise FileNotFoundError(f"Schema file not found: {item}")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(resolved):
        if path not in seen:
            deduped.append(path)
            seen.add(path)

    if not deduped:
        raise FileNotFoundError("No schema files resolved from provided --schema values.")

    for path in deduped:
        path_str = str(path)
        if any(ch in path_str for ch in "*?[]"):
            raise RuntimeError(f"[apply_schema] BUG: unresolved glob in resolved schema files: {path_str}")

    return deduped


def find_inherited_owns_redeclarations(schema_paths: list[Path]) -> list[str]:
    """Detect duplicate/inherited `owns` declarations that will fail on TypeDB 3."""
    block_re = re.compile(r"entity\s+([a-zA-Z0-9_-]+)(?:\s+sub\s+([a-zA-Z0-9_-]+))?\s*,(.*?);", re.S)
    owns_re = re.compile(r"owns\s+([a-zA-Z0-9_-]+)(?:\s+([^,;\n]+))?")

    declarations: dict[tuple[str, str], list[dict[str, object]]] = {}

    for path in schema_paths:
        content = path.read_text(encoding="utf-8")
        for entity, supertype, body in block_re.findall(content):
            for attribute, suffix in owns_re.findall(body):
                declarations.setdefault((entity, attribute), []).append(
                    {
                        "supertype": supertype,
                        "specialised": "@card" in (suffix or ""),
                        "path": str(path),
                    }
                )

    issues: list[str] = []
    declaration_keys = set(declarations.keys())
    for (entity, attribute), items in declarations.items():
        if len(items) > 1:
            paths = ", ".join(sorted({str(item["path"]) for item in items}))
            issues.append(f"{entity} declares owns {attribute} in multiple files: {paths}")

        for item in items:
            supertype = item["supertype"]
            if not supertype:
                continue
            if (supertype, attribute) not in declaration_keys:
                continue
            if item["specialised"]:
                continue
            issues.append(
                f"{entity} redeclares inherited owns {attribute} from {supertype} without specialisation "
                f"(file: {item['path']})"
            )

    return issues


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


def apply_schema(driver, db: str, schema_paths: list[Path]):
    for schema_path in schema_paths:
        schema = schema_path.read_text(encoding="utf-8")
        with driver.transaction(db, TransactionType.SCHEMA) as tx:
            tx.query(schema).resolve()
            tx.commit()
        print(f"[apply_schema] schema applied: {schema_path}")


def parse_undefine_owns_spec(spec: str) -> tuple[str, str]:
    parts = spec.split(":", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            "Invalid --undefine-owns spec. Expected format '<entity>:<attribute>', "
            f"got: {spec}"
        )
    return parts[0].strip(), parts[1].strip()


def migrate_undefine_owns(driver, db: str, specs: list[str]):
    for spec in specs:
        entity, attribute = parse_undefine_owns_spec(spec)
        query = f"undefine owns {attribute} from {entity};"
        try:
            with driver.transaction(db, TransactionType.SCHEMA) as tx:
                tx.query(query).resolve()
                tx.commit()
            print(f"[apply_schema] migration applied: {query}")
        except Exception as exc:
            print(
                "[apply_schema] migration skipped/failed (likely already aligned schema): "
                f"{query} error={exc}"
            )


def main():
    p = argparse.ArgumentParser(description="Apply TypeDB schema (local Core or Cloud TLS).")
    p.add_argument(
        "--schema",
        action="append",
        default=None,
        help="Schema file path or glob. May be passed multiple times.",
    )
    p.add_argument("--database", default=os.getenv("TYPEDB_DATABASE", "scientific_knowledge"))
    p.add_argument("--address", default=os.getenv("TYPEDB_ADDRESS"))
    p.add_argument("--host", default=os.getenv("TYPEDB_HOST", "localhost"))
    p.add_argument("--port", default=os.getenv("TYPEDB_PORT", "1729"))
    p.add_argument("--username", default=os.getenv("TYPEDB_USERNAME", "admin"))
    p.add_argument("--password", default=os.getenv("TYPEDB_PASSWORD", "password"))
    p.add_argument("--recreate", action="store_true", help="Delete and recreate the database before applying.")
    p.add_argument(
        "--undefine-owns",
        action="append",
        default=[],
        help=(
            "Run guarded migration before schema apply. Repeatable format: "
            "<entity>:<attribute> (for example: validation-evidence:template-id)"
        ),
    )
    args = p.parse_args()

    tls = env_bool("TYPEDB_TLS", "false")
    ca_path = os.getenv("TYPEDB_ROOT_CA_PATH") or None

    raw_schema_args = args.schema or [os.getenv("TYPEDB_SCHEMA", "src/schema/scientific_knowledge.tql")]
    schema_paths = resolve_schema_files(raw_schema_args)

    print("[apply_schema] resolved schema files:")
    for path in schema_paths:
        print(f"  - {path}")

    redeclaration_issues = find_inherited_owns_redeclarations(schema_paths)
    if redeclaration_issues:
        for issue in redeclaration_issues:
            print(f"[apply_schema] ERROR: {issue}")
        raise ValueError("Resolved schema set contains inherited owns redeclaration(s).")

    address = args.address if args.address else f"{args.host}:{args.port}"

    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    if is_ci and (not address or address == ":"):
        print("[apply_schema] SKIP: Skipping Cloud deployment in CI (secrets missing for branch/PR)")
        return 0

    print(f"[apply_schema] connecting to {address} tls={tls} ca={ca_path}")

    driver = connect_with_retries(address, args.username, args.password, tls, ca_path)
    try:
        if args.recreate:
            if driver.databases.contains(args.database):
                driver.databases.get(args.database).delete()
                print(f"[apply_schema] database deleted: {args.database}")

        ensure_database(driver, args.database)

        if args.undefine_owns:
            migrate_undefine_owns(driver, args.database, args.undefine_owns)

        apply_schema(driver, args.database, schema_paths)
    finally:
        driver.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[apply_schema] ERROR: {e}")
        sys.exit(1)
