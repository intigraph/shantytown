#!/usr/bin/env python3
"""Generate Shantytown's skill/docs primer copies; --check never writes."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "<!-- BEGIN st prime -->\n", "<!-- END st prime -->"


def generated(text, primer, depth):
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END, start)
    body = "".join(("#" * depth if line.startswith("#") else "") + line + "\n"
                   for line in primer.splitlines())
    return text[:start] + body + text[end:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    primer = (ROOT / "shantytown/primer.md").read_text()
    stale = []
    for path, depth in [(ROOT / "docs/prime.md", 1), (ROOT / "skills/shantytown/SKILL.md", 2)]:
        current = path.read_text()
        expected = generated(current, primer, depth)
        if expected != current:
            stale.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.write_text(expected)
    if stale and args.check:
        parser.exit(1, "Stale primer copies: " + ", ".join(stale) +
                    "; run python3 scripts/sync-primer.py\n")


if __name__ == "__main__":
    main()
