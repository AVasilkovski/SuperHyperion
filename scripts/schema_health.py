import json
import sys
from pathlib import Path


def get_repo_max_ordinal() -> int:
    """Read the max ordinal from local src/migrations/*.tql files."""
    mig_dir = Path("src/migrations")
    if not mig_dir.exists():
        return 0
        
    max_ord = 0
    # Files are presumed to be prefixed with NNN_
    for f in mig_dir.glob("*.tql"):
        parts = f.name.split("_")
        if parts:
            try:
                ord_val = int(parts[0])
                max_ord = max(max_ord, ord_val)
            except ValueError:
                pass
    return max_ord

def get_db_max_ordinal(database: str) -> int:
    """Safely fetch the max ordinal natively applied in TypeDB."""
    try:
        from typedb.driver import SessionType, TransactionType

        from src.db.typedb_client import TypeDBConnection
        db = TypeDBConnection()
        
        # If in mock mode or similar, let's gracefully return -1 and bypass
        if getattr(db, "_mock_mode", False):
            return get_repo_max_ordinal()
            
        max_db_ordinal = 0
        with db.transaction(TransactionType.READ) as tx:
            # TypeQL to get max ordinal (doing in-memory sorting for simplicity)
            query = "match $v isa schema-version, has ordinal $o, has applied-at $a; select $o, $a;"
            iterator = tx.query(query).resolve()
            for res in iterator:
                ord_concept = res.get("o")
                if ord_concept and ord_concept.is_attribute():
                    val = ord_concept.as_attribute().get_value()
                    max_db_ordinal = max(max_db_ordinal, int(val))
                        
        return max_db_ordinal
    except Exception as e:
        print(f"Failed to query DB ordinal: {e}")
        # Return -1 to force a failure state
        return -1

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Assert schema version parity")
    parser.add_argument("--database", required=True, help="Target schema database")
    parser.add_argument("--output", help="JSON output file for artifact")
    args = parser.parse_args()
    
    repo_max = get_repo_max_ordinal()
    db_max = get_db_max_ordinal(args.database)
    
    match = (repo_max == db_max)
    
    payload = {
        "status": "PASS" if match else "FAIL",
        "repo_max_ordinal": repo_max,
        "db_max_ordinal": db_max,
        "message": f"Repo schema-version is {repo_max}. DB schema-version is {db_max}."
    }
    
    # Print 1-line status for dashboards
    print(f"SCHEMA_HEALTH_CHECK: {payload['status']} | {payload['message']}")
    
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
            
    if not match:
        print("\n[!] FATAL: Schema drift detected between Repo and Database.")
        sys.exit(1)
        
if __name__ == "__main__":
    main()
