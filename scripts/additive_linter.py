#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Prevent destructive schema changes.")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    allow_destructive = os.environ.get("ALLOW_DESTRUCTIVE_SCHEMA", "false").lower() == "true"
    is_dev = os.environ.get("SUPERHYPERION_ENV", "").lower() == "dev"
    override_allowed = allow_destructive and is_dev

    cmd = ["git", "diff", "-U0", args.base, args.head]
    try:
        diff_out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"[additive_linter] Error running git diff: {e.output}")
        # Not exiting 1 here immediately to avoid failing when branches aren't fetched properly in some basic CI checkouts without explicit handling,
        # but let's assume standard behavior is to fail if we can't diff.
        return 1
    except FileNotFoundError:
        print("[additive_linter] git command not found")
        return 1

    violations = []
    current_file = None

    for line in diff_out.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("---"):
            parts = line.split(" ", 1)
            if len(parts) > 1:
                fpath = parts[1][2:] if parts[1].startswith("a/") or parts[1].startswith("b/") else parts[1]
                if fpath.endswith(".tql"):
                    current_file = fpath
                else:
                    current_file = None
            continue
            
        if current_file and line.startswith("-") and not line.startswith("---"):
            content = line[1:].strip()
            if not content or content.startswith("#"):
                continue
                
            content_lower = content.lower()
            is_violation = False
            reason = ""
            
            if "undefine" in content_lower:
                is_violation = True
                reason = "contains 'undefine'"
            else:
                for kw in ["sub", "owns", "plays", "relates", "key"]:
                    # Match word boundaries to prevent matching 'subject' for 'sub' etc.
                    if re.search(rf'\b{kw}\b', content_lower):
                        is_violation = True
                        reason = f"contains structural keyword '{kw}'"
                        break
            
            if is_violation:
                violations.append((current_file, content, reason))

    if not violations:
        print("[additive_linter] PASS: No destructive schema changes detected.")
        return 0

    # Ensure deterministic ordering
    violations.sort(key=lambda x: (x[0], x[1]))

    print("[additive_linter] FAIL: Destructive schema changes detected:")
    for fpath, snippet, reason in violations:
        print(f"  - {fpath}: {reason} -> `{snippet}`")

    if override_allowed:
        print("\n[additive_linter] WARNING: Override active (ALLOW_DESTRUCTIVE_SCHEMA=true and SUPERHYPERION_ENV=dev). Allowing changes.")
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())
