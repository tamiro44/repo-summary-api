"""File scoring and filtering heuristics for repository analysis.

Assigns a numeric priority score to each file in a repository tree so that
the most informative files are downloaded and included in the LLM context
first.  Lower score == higher priority.
"""

from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------

EXCLUDED_DIRS: set[str] = {
    "node_modules",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".env",
    "eggs",
    ".eggs",
    "bower_components",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
    "site-packages",
}

EXCLUDED_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".mkv",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".a",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".DS_Store",
}

EXCLUDED_FILENAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
}

MAX_FILE_SIZE = 512_000  # 500 KB — skip likely generated / binary blobs


def is_excluded(path: str, size: int) -> bool:
    """Return True if the file should be skipped entirely."""
    parts = path.split("/")

    # Any path segment in the excluded dirs set
    for part in parts[:-1]:
        if part in EXCLUDED_DIRS:
            return True

    filename = parts[-1]
    if filename in EXCLUDED_FILENAMES:
        return True

    _, ext = os.path.splitext(filename)
    if ext.lower() in EXCLUDED_EXTENSIONS:
        return True

    if size > MAX_FILE_SIZE:
        return True

    return False


# ---------------------------------------------------------------------------
# Scoring rules (lower = more important)
# ---------------------------------------------------------------------------

_README_RE = re.compile(r"^readme(\.\w+)?$", re.IGNORECASE)
_MANIFEST_NAMES: set[str] = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "CMakeLists.txt",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
_ENTRY_NAMES: set[str] = {
    "main.py",
    "app.py",
    "index.js",
    "index.ts",
    "server.py",
    "manage.py",
    "cli.py",
    "run.py",
    "__main__.py",
}
_TEST_INDICATORS = ("test_", "_test.", "spec.", ".test.", ".spec.", "tests/", "test/")


def score_file(path: str) -> float:
    """Return a priority score for *path*.  Lower is better."""
    filename = path.split("/")[-1]
    depth = path.count("/")

    # --- tier 0: README at root ---
    if depth == 0 and _README_RE.match(filename):
        return 0.0

    # --- tier 1: manifest / config files ---
    if filename in _MANIFEST_NAMES:
        return 10.0 + depth

    # --- tier 2: README deeper in tree ---
    if _README_RE.match(filename):
        return 20.0 + depth

    # --- tier 3: entry-point files ---
    if filename in _ENTRY_NAMES:
        return 30.0 + depth

    # --- tier 4: top-level source files ---
    if depth <= 1:
        return 40.0

    # --- tier 5: tests ---
    lower = path.lower()
    if any(ind in lower for ind in _TEST_INDICATORS):
        return 80.0 + depth

    # --- tier 6: everything else, prefer shallow ---
    return 60.0 + depth
