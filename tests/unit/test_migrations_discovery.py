import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts')))
import migrate


def test_validates_ordinal_parsing(tmp_path):
    (tmp_path / "001_init.tql").write_text("define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;")
    (tmp_path / "002_next.tql").write_text("define something;")
    
    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "false")
        migrations = migrate.get_migrations(tmp_path)
        assert len(migrations) == 2
        assert migrations[0][0] == 1
        assert migrations[1][0] == 2

def test_rejects_duplicate_ordinals(tmp_path):
    (tmp_path / "001_init.tql").write_text("define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;")
    (tmp_path / "001_other.tql").write_text("define something;")
    
    with pytest.raises(ValueError, match="Duplicate migration ordinal detected: 1"):
         migrate.get_migrations(tmp_path)

def test_enforces_filename_format(tmp_path):
    (tmp_path / "001_init.tql").write_text("define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;")
    (tmp_path / "badname.tql").write_text("define something;")
    
    with pytest.raises(ValueError, match="Invalid migration filename format: badname.tql. Must be NNN_name.tql"):
         migrate.get_migrations(tmp_path)

def test_gap_detection_fails_by_default(tmp_path):
    (tmp_path / "001_init.tql").write_text("define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;")
    (tmp_path / "003_skip.tql").write_text("define something;")
    
    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "false")
        with pytest.raises(ValueError, match="Migration gap detected: expected 2, got 3"):
             migrate.get_migrations(tmp_path)
             
def test_gap_detection_passes_with_override(tmp_path):
    (tmp_path / "001_init.tql").write_text("define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;")
    (tmp_path / "003_skip.tql").write_text("define something;")
    
    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "true")
        migrations = migrate.get_migrations(tmp_path)
        assert len(migrations) == 2
        assert migrations[1][0] == 3

def test_validates_001_preflight_check(tmp_path):
    (tmp_path / "001_init.tql").write_text("define something else;")
    
    with pytest.raises(ValueError, match="Migration 001 must contain 'schema_version' definitions"):
         migrate.get_migrations(tmp_path)
