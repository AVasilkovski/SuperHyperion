import os
import sys
from unittest.mock import patch

# Adjust path to import the linter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts')))
import additive_linter


def test_linter_passes_on_benign_diff():
    diff_output = """--- a/src/schema/scientific_knowledge.tql
+++ b/src/schema/scientific_knowledge.tql
@@ -10,3 +10,3 @@
-  # This is a benign comment removal
+  # This is a new comment
+  has new-attr;
"""
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = diff_output
        with patch.object(sys, 'argv', ['additive_linter.py']):
            assert additive_linter.main() == 0

def test_linter_fails_on_undefine():
    diff_output = """--- a/src/schema/scientific_knowledge.tql
+++ b/src/schema/scientific_knowledge.tql
@@ -10,3 +10,3 @@
-  undefine some-rule;
+  define new-rule;
"""
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = diff_output
        with patch.object(sys, 'argv', ['additive_linter.py']):
            assert additive_linter.main() == 1

def test_linter_fails_on_structural_keywords():
    diff_output = """--- a/src/schema/scientific_knowledge.tql
+++ b/src/schema/scientific_knowledge.tql
@@ -10,3 +10,3 @@
-  owns validation-evidence;
+  owns new-evidence;
"""
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = diff_output
        with patch.object(sys, 'argv', ['additive_linter.py']):
            assert additive_linter.main() == 1

def test_linter_override_allowed_in_dev_env():
    diff_output = """--- a/src/schema/scientific_knowledge.tql
+++ b/src/schema/scientific_knowledge.tql
@@ -10,3 +10,3 @@
-  undefine some-rule;
"""
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = diff_output
        with patch.dict(os.environ, {"ALLOW_DESTRUCTIVE_SCHEMA": "true", "SUPERHYPERION_ENV": "dev"}):
            with patch.object(sys, 'argv', ['additive_linter.py']):
                assert additive_linter.main() == 0

def test_linter_override_prevented_outside_dev_env():
    diff_output = """--- a/src/schema/scientific_knowledge.tql
+++ b/src/schema/scientific_knowledge.tql
@@ -10,3 +10,3 @@
-  undefine some-rule;
"""
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = diff_output
        with patch.dict(os.environ, {"ALLOW_DESTRUCTIVE_SCHEMA": "true", "SUPERHYPERION_ENV": "prod"}):
            with patch.object(sys, 'argv', ['additive_linter.py']):
                assert additive_linter.main() == 1
