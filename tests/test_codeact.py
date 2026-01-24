"""
CodeAct Sandbox Security Tests

Verifies that the sandbox blocks dangerous operations.
"""

import pytest
from src.agents.codeact_executor import CodeActExecutor, BLOCKED_PATTERNS


class TestCodeActSecurity:
    """Test suite for CodeAct sandbox security."""
    
    @pytest.fixture
    def executor(self):
        """Create a CodeAct executor for testing."""
        exec = CodeActExecutor()
        exec.start()
        yield exec
        exec.stop()
    
    # ============================================
    # Validation Tests (No Execution)
    # ============================================
    
    def test_blocks_os_system(self):
        """Should block os.system calls."""
        code = "import os; os.system('whoami')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "os.system" in error
    
    def test_blocks_subprocess(self):
        """Should block subprocess module."""
        code = "import subprocess; subprocess.run(['ls'])"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "subprocess" in error
    
    def test_blocks_eval(self):
        """Should block eval function."""
        code = "eval('__import__(\"os\").system(\"rm -rf /\")')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "eval" in error
    
    def test_blocks_exec(self):
        """Should block exec function."""
        code = "exec('import os')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "exec" in error
    
    def test_blocks_dunder_import(self):
        """Should block __import__ function."""
        code = "__import__('os').system('whoami')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "__import__" in error
    
    def test_blocks_file_write(self):
        """Should block file write operations."""
        code = "open('/etc/passwd', 'w').write('hacked')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
    
    def test_blocks_shutil_rmtree(self):
        """Should block shutil.rmtree."""
        code = "import shutil; shutil.rmtree('/')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "shutil.rmtree" in error
    
    def test_blocks_os_remove(self):
        """Should block os.remove."""
        code = "import os; os.remove('/important/file')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "os.remove" in error
    
    def test_blocks_network_requests(self):
        """Should block requests library."""
        code = "import requests; requests.get('http://evil.com')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "requests" in error
    
    def test_blocks_socket(self):
        """Should block socket operations."""
        code = "import socket; s = socket.socket()"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "socket" in error
    
    def test_blocks_httpx(self):
        """Should block httpx library."""
        code = "import httpx; httpx.get('http://evil.com')"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert not is_safe
        assert "httpx" in error
    
    # ============================================
    # Safe Code Tests
    # ============================================
    
    def test_allows_math(self):
        """Should allow math operations."""
        code = "import math; print(math.sqrt(16))"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe
        assert error is None
    
    def test_allows_numpy(self):
        """Should allow numpy operations."""
        code = "import numpy as np; print(np.mean([1, 2, 3]))"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe
    
    def test_allows_pandas(self):
        """Should allow pandas operations."""
        code = "import pandas as pd; df = pd.DataFrame({'a': [1, 2]})"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe
    
    def test_allows_statistics(self):
        """Should allow statistics module."""
        code = "import statistics; print(statistics.mean([1, 2, 3]))"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe
    
    def test_allows_json(self):
        """Should allow json module."""
        code = "import json; print(json.dumps({'a': 1}))"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe
    
    def test_allows_file_read(self):
        """Should allow reading files."""
        code = "open('/tmp/test.txt', 'r').read()"
        executor = CodeActExecutor()
        is_safe, error = executor.validate_code(code)
        assert is_safe  # Read mode is allowed
    
    # ============================================
    # Execution Tests (With Kernel)
    # ============================================
    
    @pytest.mark.slow
    def test_execution_safe_code(self, executor):
        """Should execute safe code successfully."""
        result = executor.execute("print(2 + 2)")
        assert result.success
        assert "4" in result.stdout
    
    @pytest.mark.slow
    def test_execution_blocks_dangerous_code(self, executor):
        """Should block dangerous code during execution."""
        result = executor.execute("import os; os.system('ls')")
        assert not result.success
        assert "Security validation failed" in result.error
    
    @pytest.mark.slow
    def test_execution_numpy_computation(self, executor):
        """Should execute numpy computations."""
        result = executor.execute("""
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(f"Mean: {np.mean(arr)}, Std: {np.std(arr)}")
""")
        assert result.success
        assert "Mean:" in result.stdout
    
    @pytest.mark.slow
    def test_execution_statistics(self, executor):
        """Should execute statistical computations."""
        result = executor.execute("""
import statistics
data = [2.75, 1.75, 1.25, 0.25, 0.5, 1.25, 3.5]
print(f"Mean: {statistics.mean(data):.2f}")
print(f"Stdev: {statistics.stdev(data):.2f}")
""")
        assert result.success
        assert "Mean:" in result.stdout
        assert "Stdev:" in result.stdout


class TestBlockedPatterns:
    """Test that all blocked patterns are correctly defined."""
    
    def test_all_patterns_are_valid_regex(self):
        """All blocked patterns should be valid regex."""
        import re
        for pattern in BLOCKED_PATTERNS:
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern: {pattern} - {e}")
    
    def test_sufficient_patterns_defined(self):
        """Should have minimum number of blocked patterns."""
        assert len(BLOCKED_PATTERNS) >= 10, "Should block at least 10 dangerous patterns"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
