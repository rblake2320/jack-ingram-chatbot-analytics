"""Offline source gates: import/compile, credential literals and local Markdown links."""

import compileall
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"(?:sk-ant-api\d+-[A-Za-z0-9_-]{20,}|pplx-[A-Za-z0-9]{20,}|fc-[a-f0-9]{24,})")
LINK = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def main():
    errors = []
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    for name in set(paths):
        path = ROOT / name
        if not path.is_file() or path.suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        if SECRET.search(text):
            errors.append("Credential-shaped literal: " + name)  # Never echo the secret.
        if path.suffix == ".md":
            for target in LINK.findall(text):
                target = target.strip("<>").split("#")[0]
                if not target or "://" in target or target.startswith(("mailto:", "tel:", "/")):
                    continue
                if not (path.parent / target).exists():
                    errors.append("Missing local link in " + name + ": " + target)
    if not compileall.compile_dir(ROOT / "src", quiet=1):
        errors.append("Python compilation failed")
    if errors:
        print("\n".join(sorted(set(errors))))
        return 1
    print("Worked: Python compiles, no credential-shaped literals, local Markdown links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
