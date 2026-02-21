#!/usr/bin/env python3
import argparse
import glob
import os
import re
import sys
import time
from pathlib import Path


def env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def resolve_schema_files(schema_args: list[str]) -> list[Path]:
    """Resolve schema file arguments (paths and/or globs) deterministically."""
    if not schema_args:
        raise ValueError("No --schema provided")

    cleaned: list[str] = []
    for raw in schema_args:
        s = (raw or "").strip()
        if not s:
            raise ValueError("Empty --schema argument is invalid")
        if "***" in s:
            raise FileNotFoundError(f"Invalid schema glob pattern (triple-star): {s}")
        cleaned.append(s)

    resolved: list[Path] = []
    for item in cleaned:
        has_glob_chars = any(char in item for char in "*?[")
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

    # Invariant: resolved must be concrete file paths, not patterns
    for path in deduped:
        path_str = str(path)
        if any(ch in path_str for ch in ["*", "?", "[", "]"]):
            raise ValueError(f"[apply_schema] BUG: unresolved glob in resolved schema files: {path_str}")
        if not path.is_file():
             raise FileNotFoundError(f"Schema file not found: {path_str}")

    return deduped


def parse_canonical_caps(schema_text: str) -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
    """Parse schema text to extract parent/child hierarchy, owns, and plays."""
    parent_of: dict[str, str] = {}
    owns_of: dict[str, set[str]] = {}
    plays_of: dict[str, set[str]] = {}

    import re
    # Strip comments robustly
    schema_text = re.sub(r"#.*", "", schema_text, flags=re.MULTILINE)
    
    # Extract entity/relation blocks
    # Pattern: \b(entity|relation)\b <name> [ \bsub\b <parent>] <body-until-semicolon> ;
    block_re = re.compile(r"\b(entity|relation)\b\s+([a-zA-Z0-9_-]+)(?:\s+\bsub\b\s+([a-zA-Z0-9_-]+))?\s*(.*?);", re.S)
    owns_re = re.compile(r"\bowns\b\s+([a-zA-Z0-9_-]+)")
    plays_re = re.compile(r"\bplays\b\s+([a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+)")

    for block_type, entity_name, supertype, body in block_re.findall(schema_text):
        if supertype:
            supertype = supertype.strip()
            # If it's a structural 'sub entity' or 'sub relation', we ignore it for capability mapping
            if supertype not in ("entity", "relation"):
                parent_of[entity_name] = supertype
            
        owns_of.setdefault(entity_name, set())
        for match in owns_re.findall(body):
            owns_of[entity_name].add(match)
            
        plays_of.setdefault(entity_name, set())
        for match in plays_re.findall(body):
            plays_of[entity_name].add(match)

    return parent_of, owns_of, plays_of


def compute_transitive_subtypes(parent_of: dict[str, str]) -> dict[str, set[str]]:
    """Compute transitive subtypes for every entity that has subtypes."""
    children_of: dict[str, set[str]] = {}
    for child, parent in parent_of.items():
        children_of.setdefault(parent, set()).add(child)
        
    subtypes: dict[str, set[str]] = {}
    
    def get_all_subtypes(entity: str) -> set[str]:
        if entity in subtypes:
            return subtypes[entity]
        direct_children = children_of.get(entity, set())
        all_children = set(direct_children)
        for child in direct_children:
            all_children.update(get_all_subtypes(child))
        subtypes[entity] = all_children
        return all_children
        
    for parent in list(children_of.keys()):
        get_all_subtypes(parent)
        
    return subtypes


def plan_auto_migrations(
    parent_of: dict[str, str], owns_of: dict[str, set[str]], plays_of: dict[str, set[str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Plan undefines for capabilities inherited from supertypes onto subtypes."""
    undefine_owns_specs: list[tuple[str, str]] = []
    undefine_plays_specs: list[tuple[str, str]] = []
    
    subtypes = compute_transitive_subtypes(parent_of)
    
    for supertype, attrs in owns_of.items():
        if supertype not in subtypes:
            continue
        for child in subtypes[supertype]:
            for attr in attrs:
                undefine_owns_specs.append((child, attr))

    for supertype, roles in plays_of.items():
        if supertype not in subtypes:
            continue
        for child in subtypes[supertype]:
            for role in roles:
                undefine_plays_specs.append((child, role))
                
    return undefine_owns_specs, undefine_plays_specs


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
    from typedb.driver import TransactionType
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
    from typedb.driver import TransactionType
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


def parse_undefine_plays_spec(spec: str) -> tuple[str, str]:
    parts = spec.split(":", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            "Invalid --undefine-plays spec. Expected format '<type>:<relation:role>', "
            f"got: {spec}"
        )
    return parts[0].strip(), parts[1].strip()


def migrate_undefine_plays(driver, db: str, specs: list[str]):
    from typedb.driver import TransactionType
    for spec in specs:
        type_label, scoped_role = parse_undefine_plays_spec(spec)
        query = f"undefine plays {scoped_role} from {type_label};"
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
    p.add_argument(
        "--undefine-plays",
        action="append",
        default=[],
        help=(
            "Run guarded role-play migration before schema apply. Repeatable format: "
            "<type>:<relation:role> (for example: validation-evidence:session-has-evidence:evidence)"
        ),
    )
    p.add_argument(
        "--auto-migrate-redeclarations",
        action="store_true",
        help="Proactively undefine inherited owns/plays from subtypes based on canonical schema.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned schema/migration actions without executing.",
    )
    args = p.parse_args()

    print(f"[apply_schema] argv: {sys.argv[1:]}")

    tls = env_bool("TYPEDB_TLS", "false")
    ca_path = os.getenv("TYPEDB_ROOT_CA_PATH") or None

    raw_schema_args = args.schema or [os.getenv("TYPEDB_SCHEMA", "src/schema/scientific_knowledge.tql")]
    schema_paths = resolve_schema_files(raw_schema_args)

    print("[apply_schema] resolved schema files:")
    for path in schema_paths:
        print(f"  - {path}")

    if args.dry_run:
        print("[apply_schema] dry-run: no changes will be applied")

    address = args.address if args.address else f"{args.host}:{args.port}"

    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    if is_ci and (not address or address == ":"):
        print("[apply_schema] SKIP: Skipping Cloud deployment in CI (secrets missing for branch/PR)")
        return 0

    if args.auto_migrate_redeclarations:
        schema_text = "\n\n".join(path.read_text(encoding="utf-8") for path in schema_paths)
        parent_of, owns_of, plays_of = parse_canonical_caps(schema_text)
        owns_specs, plays_specs = plan_auto_migrations(parent_of, owns_of, plays_of)
        print(f"[apply_schema] auto-migrate planned owns={len(owns_specs)} plays={len(plays_specs)}")
        # We'll apply these later after connecting

    if args.dry_run:
        return 0

    print(f"[apply_schema] connecting to {address} tls={tls} ca={ca_path}")

    driver = connect_with_retries(address, args.username, args.password, tls, ca_path)
    try:
        if args.recreate:
            if driver.databases.contains(args.database):
                driver.databases.get(args.database).delete()
                print(f"[apply_schema] database deleted: {args.database}")

        ensure_database(driver, args.database)

        if args.auto_migrate_redeclarations:
            # Re-read or use local specs
            migrate_undefine_owns(driver, args.database, [f"{t}:{a}" for t, a in owns_specs])
            migrate_undefine_plays(driver, args.database, [f"{t}:{r}" for t, r in plays_specs])

        if args.undefine_plays:
            print(f"[apply_schema] manual undefine plays overrides: {args.undefine_plays}")
            migrate_undefine_plays(driver, args.database, args.undefine_plays)

        if args.undefine_owns:
            print(f"[apply_schema] manual undefine owns overrides: {args.undefine_owns}")
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
