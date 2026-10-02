"""Build the Lambda deployment package, deploy/build/dharmeme.zip (SPEC.md §9).

    python scripts/build_lambda.py     # then: sam deploy, from deploy/sam/

The zip holds the handler, the dharmeme package, catalog.json, the seed memes, the
template images, the font and the dependencies as Linux wheels. The catalog ships as JSON, so the Lambda needs no PyYAML.
It is assembled in a temp folder: building in place under a synced folder (OneDrive)
can leave the dependency folders empty.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402
from dharmeme.themes import load_themes  # noqa: E402

ZIP = ROOT / "deploy" / "build" / "dharmeme.zip"
PYTHON_VERSION = "3.13"  # must match Runtime in deploy/sam/template.yaml
# boto3 is already in the Lambda runtime. Pillow draws the memes for Telegram.
DEPENDENCIES = ["anthropic", "Pillow"]
CATALOG_FIELDS = ["id", "name", "image", "format", "slots"]


def assemble(out: Path, install: bool = True) -> None:
    shutil.copytree(ROOT / "src" / "dharmeme", out / "dharmeme",
                    ignore=shutil.ignore_patterns("__pycache__", "catalog.py"))
    shutil.copy2(ROOT / "deploy" / "lambda" / "handler.py", out / "handler.py")
    shutil.copy2(ROOT / "seed" / "memes.jsonl", out / "seed.jsonl")
    shutil.copytree(ROOT / "templates" / "images", out / "images",
                    ignore=shutil.ignore_patterns(".*"))
    shutil.copy2(ROOT / "templates" / "fonts" / "Anton-Regular.ttf", out / "Anton-Regular.ttf")
    catalog = [{k: t[k] for k in CATALOG_FIELDS} for t in load_catalog()]
    (out / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (out / "themes.json").write_text(json.dumps(load_themes(), ensure_ascii=False),
                                     encoding="utf-8")
    if install:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--target", str(out), "--platform", "manylinux2014_x86_64",
             "--implementation", "cp", "--python-version", PYTHON_VERSION,
             "--only-binary=:all:", *DEPENDENCIES],
            check=True,
        )


def build(zip_path: Path = ZIP, install: bool = True) -> Path:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        out = Path(tmp) / "package"
        out.mkdir()
        assemble(out, install)
        files = sorted(p for p in out.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        if install and not any(p.parts[len(out.parts)] == "anthropic" for p in files):
            raise SystemExit("The Anthropic SDK is missing from the package.")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, p.relative_to(out).as_posix())
    print(f"Built {zip_path}: {len(files)} files, {zip_path.stat().st_size / 1e6:.1f} MB")
    return zip_path


if __name__ == "__main__":
    build()
