"""Validate public automation recipes without executing them or fetching schemas."""

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "automation-recipes"
SCHEMA_PATH = RECIPE_DIR / "schema" / "automation-recipe-v1.schema.json"


def reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant {value}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def validate_recipes(
    recipe_dir: Path, schema_path: Path = SCHEMA_PATH, *, output: TextIO
) -> int:
    try:
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as error:
        print(f"{schema_path.name}: invalid schema: {error}", file=output)
        return 1

    if not recipe_dir.is_dir():
        print(f"{recipe_dir.name}: recipe directory does not exist", file=output)
        return 1
    paths = sorted(
        path
        for path in recipe_dir.rglob("*.json")
        if path.resolve() != schema_path.resolve()
    )
    if not paths:
        print(f"{recipe_dir.name}: no recipe JSON files found", file=output)
        return 1

    # An empty registry has no retriever: unresolved references cannot use the network.
    validator = Draft202012Validator(schema, registry=Registry())
    failed = False
    for path in paths:
        name = path.relative_to(recipe_dir).as_posix()
        try:
            document = read_json(path)
            errors = sorted(
                validator.iter_errors(document),
                key=lambda error: (error.json_path, error.message),
            )
        except (OSError, ValueError, Unresolvable) as error:
            print(f"{name}: {error}", file=output)
            failed = True
            continue
        for error in errors:
            message = error.message.replace("\n", " ")
            print(f"{name}: {error.json_path}: {message}", file=output)
            failed = True

    if not failed:
        print(f"Validated {len(paths)} recipe(s).", file=output)
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipes-dir",
        type=Path,
        default=RECIPE_DIR,
        help="directory to scan recursively (default: repository automation-recipes)",
    )
    args = parser.parse_args()
    return validate_recipes(args.recipes_dir, output=sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
