import re
import shutil
import subprocess
import sys
from pathlib import Path


SECRET_PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "Telegram bot token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
}

SKIPPED_SUFFIXES = {
    ".db",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
}


def main() -> int:
    tracked_files = _files_to_scan()

    findings = []
    for file_name in tracked_files:
        path = Path(file_name)
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{file_name}: possible {label}")

    if findings:
        print("Secret scan failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Secret scan passed.")
    return 0


def _files_to_scan() -> list[str]:
    if shutil.which("git"):
        return subprocess.check_output(
            ["git", "ls-files"],
            text=True,
            encoding="utf-8",
        ).splitlines()

    ignored_dirs = {".git", "__pycache__", ".pytest_cache", "data"}
    return [
        str(path)
        for path in Path(".").rglob("*")
        if path.is_file() and not ignored_dirs.intersection(path.parts)
    ]


if __name__ == "__main__":
    sys.exit(main())
