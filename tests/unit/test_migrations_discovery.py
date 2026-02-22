import os
import sys
from unittest.mock import MagicMock

# Mock typedb.driver before importing migrate
mock_typedb = MagicMock()
sys.modules["typedb"] = mock_typedb
sys.modules["typedb.driver"] = mock_typedb.driver

import pytest  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))
import migrate  # noqa: E402


def test_validates_ordinal_parsing(tmp_path):
    (tmp_path / "001_init.tql").write_text(
        "define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;"
    )
    (tmp_path / "002_next.tql").write_text("define something;")

    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "false")
        migrations = migrate.get_migrations(tmp_path)
        assert len(migrations) == 2
        assert migrations[0][0] == 1
        assert migrations[1][0] == 2


def test_rejects_duplicate_ordinals(tmp_path):
    (tmp_path / "001_init.tql").write_text(
        "define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;"
    )
    (tmp_path / "001_other.tql").write_text("define something;")

    with pytest.raises(ValueError, match="Duplicate migration ordinal detected: 1"):
        migrate.get_migrations(tmp_path)


def test_enforces_filename_format(tmp_path):
    (tmp_path / "001_init.tql").write_text(
        "define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;"
    )
    (tmp_path / "badname.tql").write_text("define something;")

    with pytest.raises(
        ValueError, match="Invalid migration filename format: badname.tql. Must be NNN_name.tql"
    ):
        migrate.get_migrations(tmp_path)


def test_gap_detection_fails_by_default(tmp_path):
    (tmp_path / "001_init.tql").write_text(
        "define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;"
    )
    (tmp_path / "003_skip.tql").write_text("define something;")

    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "false")
        with pytest.raises(ValueError, match="Migration gap detected: expected 2, got 3"):
            migrate.get_migrations(tmp_path)


def test_gap_detection_passes_with_override(tmp_path):
    (tmp_path / "001_init.tql").write_text(
        "define schema_version sub entity, owns ordinal, owns git-commit, owns applied-at;"
    )
    (tmp_path / "003_skip.tql").write_text("define something;")

    with pytest.MonkeyPatch.context() as m:
        m.setenv("MIGRATIONS_ALLOW_GAPS", "true")
        migrations = migrate.get_migrations(tmp_path)
        assert len(migrations) == 2
        assert migrations[1][0] == 3


def test_validates_001_preflight_check(tmp_path):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    # Missing schema_version definitions
    f1 = mig_dir / "001_v1.tql"
    f1.write_text("define entity foo;", encoding="utf-8")

    with pytest.raises(ValueError, match="Migration 001 must contain 'schema_version'"):
        migrate.get_migrations(mig_dir)


def test_enforces_migration_hygiene(tmp_path):
    mig_file = tmp_path / "004_bad.tql"
    mig_file.write_text("insert $x isa foo;", encoding="utf-8")

    mock_driver = MagicMock()
    with pytest.raises(ValueError, match="Migration hygiene violation"):
        migrate.apply_migration(mock_driver, "db", mig_file, 4, dry_run=True)

    # Valid starts
    for kw in ["define", "undefine", "redefine"]:
        mig_file = tmp_path / f"005_{kw}.tql"
        mig_file.write_text(f"{kw} entity bar;", encoding="utf-8")
        # Should NOT raise ValueError for hygiene (might raise for other things if not dry-run)
        migrate.apply_migration(mock_driver, "db", mig_file, 5, dry_run=True)
