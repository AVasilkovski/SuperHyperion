
from src.agents.codeact_executor import CodeActExecutor, BLOCKED_PATTERNS
import re

print(f"Loaded {len(BLOCKED_PATTERNS)} patterns.")
for p in BLOCKED_PATTERNS:
    print(f"Pattern: {p}")

code = "import os; os.system('whoami')"
print(f"\nTesting code: {code}")

executor = CodeActExecutor()
is_safe, error = executor.validate_code(code)
print(f"is_safe: {is_safe}")
print(f"error: {error}")

if is_safe:
    print("FAILURE: Should verify as unsafe!")
else:
    print("SUCCESS: Verified as unsafe.")
