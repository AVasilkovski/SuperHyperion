
import re

BLOCKED_PATTERNS = [
    r'\bos\.system\b',
    r'\bsubprocess\b',
    r'\b__import__\b',
    r'\beval\b',
    r'\bexec\b',
    r'\bopen\s*\([^)]*[\'"][wa]',  # open() with write/append mode
    r'\bshutil\.rmtree\b',
    r'\bos\.remove\b',
    r'\bos\.unlink\b',
    r'\bos\.rmdir\b',
    r'\bpathlib.*\.unlink\b',
    r'\bpathlib.*\.rmdir\b',
    r'\brequests\.(get|post|put|delete|patch)\b',  # Block network requests
    r'\bhttpx\b',
    r'\burllib\b',
    r'\bsocket\b',
]

def test_pattern(code, pattern):
    match = re.search(pattern, code)
    print(f"Pattern: {pattern} | Code: {code} | Match: {match}")

print("Testing os.system...")
test_pattern("import os; os.system('whoami')", r'\bos\.system\b')

print("\nTesting eval...")
test_pattern("eval('__import__(\"os\").system(\"rm -rf /\")')", r'\beval\b')

print("\nTesting shutil.rmtree...")
test_pattern("import shutil; shutil.rmtree('/')", r'\bshutil\.rmtree\b')

print("\nTesting os.remove...")
test_pattern("import os; os.remove('/important/file')", r'\bos\.remove\b')
