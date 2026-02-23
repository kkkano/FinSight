"""Simple encoding sanity scanner for source files.

Usage:
  python scripts/fix_encoding.py
"""

from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = [PROJECT_ROOT / "backend", PROJECT_ROOT / "frontend" / "src"]
FILE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md"}

# Generic mojibake markers.
SUSPECT_PATTERNS = [
    r"鈥",
    r"锟",
    r"\uFFFD",
]


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root in TARGET_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in FILE_EXTENSIONS:
                files.append(path)
    return files


def scan_file(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return hits

    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for pattern in SUSPECT_PATTERNS:
            if re.search(pattern, line):
                hits.append((i, line.strip()))
                break
    return hits


def main() -> int:
    files = iter_source_files()
    total_hits = 0

    for path in files:
        hits = scan_file(path)
        if not hits:
            continue
        print(f"\n{path.relative_to(PROJECT_ROOT)}")
        for line_no, content in hits:
            print(f"  L{line_no}: {content}")
        total_hits += len(hits)

    if total_hits == 0:
        print("No suspect encoding lines found.")
    else:
        print(f"\nFound {total_hits} suspect lines.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
