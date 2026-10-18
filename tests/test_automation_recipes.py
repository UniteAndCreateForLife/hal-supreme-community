import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.validate_automation_recipes import (
    RECIPE_DIR,
    ROOT,
    SCHEMA_PATH,
    validate_recipes,
)

FIXTURES = ROOT / "tests" / "fixtures" / "automation-recipes"
SCRIPT = ROOT / "tools" / "validate_automation_recipes.py"


class RecipeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def validate(self, schema_path=SCHEMA_PATH):
        output = io.StringIO()
        result = validate_recipes(self.directory, schema_path, output=output)
        return result, output.getvalue()

    def write_recipe(self, document):
        path = self.directory / "recipe.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_merged_recipes_validate_without_network(self):
        output = io.StringIO()
        with patch("socket.socket.connect", side_effect=AssertionError("network used")):
            result = validate_recipes(RECIPE_DIR, output=output)
        self.assertEqual(result, 0, output.getvalue())
        self.assertRegex(output.getvalue(), r"Validated [1-9]\d* recipe\(s\)\.")

    def test_valid_fixture(self):
        shutil.copyfile(FIXTURES / "valid.json", self.directory / "recipe.json")
        self.assertEqual(self.validate(), (0, "Validated 1 recipe(s).\n"))

    def test_invalid_fixtures(self):
        for filename, message in [
            ("missing-required.json", "'schema_version' is a required property"),
            ("invalid-permission.json", "$.permissions.approval_policy"),
            ("malformed.json", "line 2 column 1"),
        ]:
            with self.subTest(filename=filename):
                shutil.copyfile(FIXTURES / filename, self.directory / "recipe.json")
                status, output = self.validate()
                self.assertEqual(status, 1)
                self.assertIn("recipe.json:", output)
                self.assertIn(message, output)
                self.assertNotIn("Traceback", output)

    def test_schema_constraints_are_enforced(self):
        valid = json.loads((FIXTURES / "valid.json").read_text(encoding="utf-8"))
        for field, value in [
            ("schema_version", "wrong-version"),
            ("steps", []),
            ("expected_receipts", []),
            ("recipe_id", "UPPER CASE"),
            ("unexpected", True),
        ]:
            with self.subTest(field=field):
                self.write_recipe({**valid, field: value})
                status, output = self.validate()
                self.assertEqual(status, 1, output)

    def test_recursive_scan_excludes_only_the_schema_and_reports_all_files(self):
        schema = self.directory / "schema" / "automation-recipe-v1.schema.json"
        schema.parent.mkdir()
        shutil.copyfile(SCHEMA_PATH, schema)
        nested = self.directory / "nested"
        nested.mkdir()
        shutil.copyfile(FIXTURES / "valid.json", nested / "valid.json")
        self.assertEqual(self.validate(schema), (0, "Validated 1 recipe(s).\n"))
        shutil.copyfile(FIXTURES / "malformed.json", nested / "a-invalid.json")
        shutil.copyfile(
            FIXTURES / "invalid-permission.json", schema.parent / "b-invalid.json"
        )
        status, output = self.validate(schema)
        self.assertEqual(status, 1)
        self.assertIn("nested/a-invalid.json:", output)
        self.assertIn("schema/b-invalid.json:", output)
        self.assertLess(
            output.index("nested/a-invalid.json"), output.index("schema/b-invalid.json")
        )

    def test_non_json_numbers_are_rejected_even_in_free_form_filters(self):
        valid = json.loads((FIXTURES / "valid.json").read_text(encoding="utf-8"))
        for number in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(number=number):
                valid["trigger"]["filter"] = {"value": number}
                self.write_recipe(valid)
                status, output = self.validate()
                self.assertEqual(status, 1)
                self.assertIn("non-JSON numeric constant", output)

    def test_empty_and_missing_directories_fail(self):
        self.assertEqual(self.validate()[0], 1)
        output = io.StringIO()
        self.assertEqual(validate_recipes(self.directory / "missing", output=output), 1)
        self.assertIn("directory does not exist", output.getvalue())

    def test_invalid_schema_fails_cleanly(self):
        schema = self.directory / "schema.json"
        schema.write_text('{"type": "not-a-type"}', encoding="utf-8")
        status, output = self.validate(schema)
        self.assertEqual(status, 1)
        self.assertIn("schema.json: invalid schema:", output)

    def test_remote_schema_reference_does_not_fetch(self):
        schema = self.directory / "schema.json"
        schema.write_text(
            '{"$ref": "https://example.invalid/schema"}', encoding="utf-8"
        )
        self.write_recipe({})
        with patch("socket.socket.connect", side_effect=AssertionError("network used")):
            status, output = self.validate(schema)
        self.assertEqual(status, 1)
        self.assertIn("Unresolvable", output)

    def test_cli_exit_codes_and_default_path_from_another_working_directory(self):
        command = [sys.executable, str(SCRIPT)]
        success = subprocess.run(
            command, cwd=self.directory, capture_output=True, text=True, check=False
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertRegex(success.stdout, r"Validated [1-9]\d* recipe\(s\)\.")
        shutil.copyfile(FIXTURES / "malformed.json", self.directory / "bad.json")
        failure = subprocess.run(
            command + ["--recipes-dir", str(self.directory)],
            cwd=self.directory,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(failure.returncode, 1)
        self.assertIn("bad.json:", failure.stdout)
        self.assertNotIn("Traceback", failure.stderr)


if __name__ == "__main__":
    unittest.main()
