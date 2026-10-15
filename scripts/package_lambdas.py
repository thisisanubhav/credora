"""Build a Linux/x86_64 Python 3.12 artifact locally without contacting AWS."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build" / "m8"
ARTIFACT = BUILD / "lambda.zip"
MAX_UNCOMPRESSED = 250 * 1024 * 1024
SOURCES = (
    "apps/__init__.py", "apps/api/__init__.py", "apps/api/main.py", "apps/api/aws_handler.py",
    "services/__init__.py", "services/common/__init__.py", "services/common/db.py",
    "services/common/models.py", "services/ingestion/__init__.py",
    "services/ingestion/config.py", "services/ingestion/worker.py",
)


def build() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
        "--format", "requirements-txt", "--output-file", ".build/m8/constraints.txt",
    ], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix="lambda-build-", dir=BUILD) as temporary:
        target = Path(temporary)
        subprocess.run([
            "uv", "pip", "install", "--target", str(target.relative_to(ROOT)),
            "--python-platform", "x86_64-manylinux_2_34", "--python-version", "3.12",
            "--only-binary", ":all:", "--constraint", ".build/m8/constraints.txt",
            "--requirement", "infrastructure/lambda/requirements.txt",
        ], cwd=ROOT, check=True)
        for relative in SOURCES:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        total = 0
        with ZipFile(ARTIFACT, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(target.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                total += path.stat().st_size
                if total > MAX_UNCOMPRESSED:
                    raise ValueError("Lambda uncompressed artifact exceeds 250 MiB")
                archive.write(path, path.relative_to(target))
    with ZipFile(ARTIFACT) as archive:
        names = set(archive.namelist())
        for required in ("apps/api/aws_handler.py", "services/ingestion/worker.py"):
            if required not in names:
                raise ValueError(f"missing packaged handler: {required}")
        if any(name.startswith(("tests/", ".env", "docs/")) for name in names):
            raise ValueError("unexpected test, secret, or documentation in package")
    print(f"Local Linux Lambda artifact: {ARTIFACT.relative_to(ROOT)}; {ARTIFACT.stat().st_size} bytes compressed; {total} bytes uncompressed")


if __name__ == "__main__":
    build()
