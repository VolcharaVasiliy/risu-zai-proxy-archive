"""Ensure generated provider and extension artifacts are reproducible."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(*args):
    result = subprocess.run([PYTHON, *args], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def main():
    run("scripts/generate_provider_artifacts.py", "--check")
    run("scripts/generate_extension_i18n.py", "--check")
    run("scripts/generate_provider_artifacts.py")
    run("scripts/generate_extension_i18n.py")
    run("scripts/generate_provider_artifacts.py", "--check")
    run("scripts/generate_extension_i18n.py", "--check")
    print("generated artifact tests: ok")


if __name__ == "__main__":
    main()
