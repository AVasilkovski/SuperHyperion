#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from apply_schema import parse_canonical_caps


def compare_schemas(old_text: str, new_text: str) -> tuple[int, list[str]]:
    """Compare two schema texts and return (exit_code, list of errors)."""
    old_parent_of, old_owns_of, old_plays_of = parse_canonical_caps(old_text)
    new_parent_of, new_owns_of, new_plays_of = parse_canonical_caps(new_text)

    errors = []

    # 1. Detect removed types
    old_types = set(old_parent_of.keys()) | set(old_owns_of.keys()) | set(old_plays_of.keys())
    new_types = set(new_parent_of.keys()) | set(new_owns_of.keys()) | set(new_plays_of.keys())
    
    removed_types = old_types - new_types
    for typ in removed_types:
        errors.append(f"REMOVED: Type '{typ}' was deleted.")

    # 2. Detect removed owns edges
    for typ, old_attrs in old_owns_of.items():
        if typ not in removed_types: # only report if the type still exists
            new_attrs = new_owns_of.get(typ, set())
            removed_attrs = old_attrs - new_attrs
            for attr in removed_attrs:
                errors.append(f"REMOVED: Type '{typ}' no longer owns '{attr}'.")

    # 3. Detect removed plays edges
    for typ, old_roles in old_plays_of.items():
         if typ not in removed_types:
            new_roles = new_plays_of.get(typ, set())
            removed_roles = old_roles - new_roles
            for role in removed_roles:
                errors.append(f"REMOVED: Type '{typ}' no longer plays '{role}'.")

    # 4. We omit undefine checking for now, as that relies on parse logic of the tql string itself, 
    # but the structural mapping catches the *results* of undefines conceptually if we compare full schemas.
    # We could also just regex for `undefine ` in the new schema if we want a hard block on the word.
    import re
    if re.search(r"\bundefine\b", new_text):
        errors.append("UNDEFINE: The 'undefine' keyword was found in the schema. This is forbidden in Additive-Only normal releases.")

    return (len(errors) > 0, errors)


def main():
    p = argparse.ArgumentParser(description="Additive-only migration linter.")
    p.add_argument("--base", required=True, help="Base canonical schema file (e.g. from main branch)")
    p.add_argument("--head", required=True, help="Head canonical schema file (or merged with migrations)")
    p.add_argument("--allow-breaking", action="store_true", help="Explicitly allow breaking changes (bypass linter).")
    args = p.parse_args()

    if args.allow_breaking:
        print("[additive_linter] WARNING: Linter bypassed natively via --allow-breaking. Breaking changes allowed.")
        return 0

    base_path = Path(args.base)
    head_path = Path(args.head)

    if not base_path.exists():
        print(f"[additive_linter] base schema {base_path} not found. Skipping compare.")
        return 0

    if not head_path.exists():
         print(f"[additive_linter] ERROR: head schema {head_path} not found.")
         return 1

    old_text = base_path.read_text(encoding="utf-8")
    new_text = head_path.read_text(encoding="utf-8")

    has_errors, errors = compare_schemas(old_text, new_text)

    if has_errors:
        print("====== ADDITIVE-ONLY LINTER FAILED ======")
        print("The following breaking changes were detected:")
        for err in errors:
            print(f"  - {err}")
        print("\nFix: Revert destructive schema changes.")
        print("To override manually (e.g., scheduled breaking window), use --allow-breaking.")
        return 1
    
    print("[additive_linter] OK: Canonical schema changes are strictly additive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
