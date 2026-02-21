import importlib.util
from pathlib import Path

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
