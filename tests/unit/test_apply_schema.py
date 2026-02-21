import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("apply_schema", Path("scripts/apply_schema.py"))
assert SPEC and SPEC.loader
apply_schema = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_schema)


def test_resolve_schema_files_single_canonical_schema():
    files = apply_schema.resolve_schema_files(["src/schema/scientific_knowledge.tql"])
    assert files == [Path("src/schema/scientific_knowledge.tql")]


def test_redeclaration_detector_flags_inherited_owns_without_specialisation(tmp_path: Path):
    schema_path = tmp_path / "bad_schema.tql"
    schema_path.write_text(
        """
        define
        attribute scope-lock-id, value string;
        entity evidence, owns scope-lock-id;
        entity validation-evidence sub evidence, owns scope-lock-id;
        """,
        encoding="utf-8",
    )

    issues = apply_schema.find_inherited_owns_redeclarations([schema_path])
    assert any("validation-evidence redeclares inherited owns scope-lock-id" in issue for issue in issues)


def test_redeclaration_detector_accepts_current_canonical_schema():
    issues = apply_schema.find_inherited_owns_redeclarations([Path("src/schema/scientific_knowledge.tql")])
    assert issues == []


def test_redeclaration_detector_flags_duplicate_owns_across_files(tmp_path: Path):
    first = tmp_path / "01_base.tql"
    second = tmp_path / "02_patch.tql"
    first.write_text(
        """
        define
        attribute scope-lock-id, value string;
        entity evidence, owns scope-lock-id;
        """,
        encoding="utf-8",
    )
    second.write_text(
        """
        define
        entity evidence, owns scope-lock-id;
        """,
        encoding="utf-8",
    )

    issues = apply_schema.find_inherited_owns_redeclarations([first, second])
    assert any("evidence declares owns scope-lock-id in multiple files" in issue for issue in issues)


def test_resolve_schema_files_unmatched_glob_fails_fast():
    with pytest.raises(FileNotFoundError, match="Schema glob matched no files"):
        apply_schema.resolve_schema_files(["src/schema/does-not-exist*.tql"])


def test_parse_undefine_owns_spec_requires_entity_and_attribute():
    with pytest.raises(ValueError, match="Invalid --undefine-owns spec"):
        apply_schema.parse_undefine_owns_spec("validation-evidence")


def test_redeclaration_detector_flags_template_id_inheritance_conflict(tmp_path: Path):
    schema_path = tmp_path / "legacy_schema.tql"
    schema_path.write_text(
        """
        define
        attribute template-id, value string;
        entity evidence, owns template-id;
        entity validation-evidence sub evidence, owns template-id;
        """,
        encoding="utf-8",
    )

    issues = apply_schema.find_inherited_owns_redeclarations([schema_path])
    assert any("validation-evidence redeclares inherited owns template-id" in issue for issue in issues)


def test_resolve_schema_files_rejects_invalid_triple_star_glob():
    with pytest.raises(FileNotFoundError, match="Invalid schema glob pattern"):
        apply_schema.resolve_schema_files(["src/schema/***.tql"])
