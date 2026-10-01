"""Assemble the Lambda deployment folder, deploy/build/ (SPEC.md §9).

    python scripts/build_lambda.py     # then: sam deploy, from deploy/sam/

Puts the handler, the dharmeme package, catalog.json and the seed memes side by side,
and installs the dependencies as Linux wheels so the folder can be zipped as it is.
The catalog ships as JSON, so the Lambda needs no PyYAML.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402

OUT = ROOT / "deploy" / "build"
PYTHON_VERSION = "3.13"  # must match Runtime in deploy/sam/template.yaml
# boto3 is already in the Lambda runtime, so only the Anthropic SDK is bundled.
DEPENDENCIES = ["anthropic"]
CATALOG_FIELDS = ["id", "name", "format", "slots"]


def build(out: Path = OUT, install: bool = True) -> Path:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copytree(ROOT / "src" / "dharmeme", out / "dharmeme", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "catalog.py"))
    shutil.copy2(ROOT / "deploy" / "lambda" / "handler.py", out / "handler.py")
    shutil.copy2(ROOT / "seed" / "memes.jsonl", out / "seed.jsonl")
    catalog = [{k: t[k] for k in CATALOG_FIELDS} for t in load_catalog()]
    (out / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    if install:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
             "--target", str(out), "--platform", "manylinux2014_x86_64",
             "--implementation", "cp", "--python-version", PYTHON_VERSION,
             "--only-binary=:all:", *DEPENDENCIES],
            check=True,
        )
    print(f"Built {out}")
    return out


if __name__ == "__main__":
    build()
