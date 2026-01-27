"""
CodeAct Executor

Secure sandbox for executing Python code using Jupyter kernels.
This implements the CodeAct paradigm where agents think and act in Python.
"""

import re
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import logging

from jupyter_client import KernelManager
from jupyter_client.kernelspec import NoSuchKernel

logger = logging.getLogger(__name__)


# Dangerous patterns to block
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


@dataclass
class ExecutionResult:
    """Result from code execution."""
    success: bool
    stdout: str
    stderr: str
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_count: int = 0


class CodeActExecutor:
    """
    Secure Python code executor using Jupyter kernel.
    
    Implements the CodeAct paradigm:
    - Agents write Python code as their action
    - Code is validated for safety
    - Executed in isolated Jupyter kernel
    - Results returned for agent reasoning
    """
    
    def __init__(self, kernel_name: str = "python3"):
        self.kernel_name = kernel_name
        self._km: Optional[KernelManager] = None
        self._kc = None  # Kernel client
        self._execution_count = 0
    
    def start(self):
        """Start the Jupyter kernel."""
        if self._km is None:
            try:
                self._km = KernelManager(kernel_name=self.kernel_name)
                self._km.start_kernel()
                self._kc = self._km.client()
                self._kc.start_channels()
                self._kc.wait_for_ready(timeout=30)
                logger.info(f"Jupyter kernel started: {self.kernel_name}")
                
                # Initialize with safe imports
                self._execute_setup()
                
            except NoSuchKernel:
                raise RuntimeError(f"Kernel not found: {self.kernel_name}")
    
    def _execute_setup(self):
        """Set up the kernel with allowed imports."""
        setup_code = """
import numpy as np
import pandas as pd
import math
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import statistics

# Disable dangerous modules
import sys
class BlockedModule:
    def __getattr__(self, name):
        raise ImportError("This module is blocked for security")

sys.modules['os'] = BlockedModule()
sys.modules['subprocess'] = BlockedModule()
sys.modules['shutil'] = BlockedModule()
sys.modules['socket'] = BlockedModule()
sys.modules['requests'] = BlockedModule()
sys.modules['httpx'] = BlockedModule()

print("CodeAct sandbox initialized")
"""
        self._execute_raw(setup_code)
    
    def stop(self):
        """Stop the Jupyter kernel."""
        if self._kc:
            self._kc.stop_channels()
        if self._km:
            self._km.shutdown_kernel()
            self._km = None
        logger.info("Jupyter kernel stopped")
    
    def validate_code(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate code for safety before execution.
        
        Returns:
            Tuple of (is_safe, error_message)
        """
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, code):
                return False, f"Blocked pattern detected: {pattern}"
        
        return True, None
    
    def _execute_raw(self, code: str, timeout: int = 30) -> ExecutionResult:
        """Execute code without validation (internal use only)."""
        if self._kc is None:
            self.start()
        
        self._execution_count += 1
        _msg_id = self._kc.execute(code)  # noqa: F841
        
        stdout_parts = []
        stderr_parts = []
        result = None
        error = None
        
        while True:
            try:
                msg = self._kc.get_iopub_msg(timeout=timeout)
                msg_type = msg['msg_type']
                content = msg['content']
                
                if msg_type == 'stream':
                    if content['name'] == 'stdout':
                        stdout_parts.append(content['text'])
                    elif content['name'] == 'stderr':
                        stderr_parts.append(content['text'])
                        
                elif msg_type == 'execute_result':
                    result = content['data'].get('text/plain', '')
                    
                elif msg_type == 'error':
                    error = '\n'.join(content['traceback'])
                    
                elif msg_type == 'status':
                    if content['execution_state'] == 'idle':
                        break
                        
            except Exception as e:
                error = str(e)
                break
        
        return ExecutionResult(
            success=error is None,
            stdout=''.join(stdout_parts),
            stderr=''.join(stderr_parts),
            result=result,
            error=error,
            execution_count=self._execution_count,
        )
    
    def execute(self, code: str, timeout: int = 30) -> ExecutionResult:
        """
        Execute Python code safely.
        
        Args:
            code: Python code to execute
            timeout: Maximum execution time in seconds
            
        Returns:
            ExecutionResult with stdout, stderr, and any errors
        """
        # Validate first
        is_safe, error_msg = self.validate_code(code)
        if not is_safe:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                error=f"Security validation failed: {error_msg}",
                execution_count=self._execution_count,
            )
        
        return self._execute_raw(code, timeout)
    
    def execute_and_capture(self, code: str) -> Dict[str, Any]:
        """
        Execute code and return a structured response for agent consumption.
        """
        result = self.execute(code)
        
        return {
            "success": result.success,
            "output": result.stdout + (f"\nResult: {result.result}" if result.result else ""),
            "error": result.error or result.stderr if not result.success else None,
            "execution_id": result.execution_count,
        }
    
    def reset(self):
        """Reset the kernel to clean state."""
        self.stop()
        self.start()
        logger.info("Kernel reset to clean state")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# Global executor instance
codeact = CodeActExecutor()


def execute_python(code: str) -> Dict[str, Any]:
    """Convenience function for executing Python code."""
    return codeact.execute_and_capture(code)


if __name__ == "__main__":
    # Test the executor
    with CodeActExecutor() as executor:
        # Safe code
        result = executor.execute("print(2 + 2)")
        print(f"Safe code result: {result}")
        
        # Statistical computation
        result = executor.execute("""
import statistics
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
print(f"Mean: {statistics.mean(data)}")
print(f"Stdev: {statistics.stdev(data)}")
""")
        print(f"Stats result: {result}")
        
        # Blocked code
        result = executor.execute("import os; os.system('ls')")
        print(f"Blocked code result: {result}")
