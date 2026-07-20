"""Extract class/method names from changed files and verify they exist in the codebase."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


def extract_symbols_from_diff(diff_text: str) -> set[str]:
    """Extract potential class, interface, record, and method names from a diff."""
    symbols = set()

    # Match type declarations: class/interface/record/enum TypeName
    type_pattern = r'^\+.*?\b(?:class|interface|record|enum)\s+([A-Z]\w+)'
    # Match method declarations: an access/other modifier followed by a return type
    # and a method name immediately before "(", e.g. "public void doThing(" or
    # "private Optional<Foo> findFoo(".
    method_pattern = r'^\+.*?\b(?:public|private|protected|static|final|synchronized)\b[^;{]*?\s([a-z]\w*)\s*\('

    for line in diff_text.splitlines():
        # Look at added lines only
        if line.startswith('+') and not line.startswith('+++'):
            type_match = re.search(type_pattern, line)
            if type_match:
                symbols.add(type_match.group(1))

            method_match = re.search(method_pattern, line)
            if method_match:
                symbols.add(method_match.group(1))

    return symbols


def verify_symbol_exists(symbol: str) -> bool:
    """Check if a symbol exists in the codebase using grep."""
    try:
        result = subprocess.run(
            ['grep', '-r', f'\\b{re.escape(symbol)}\\b', '--include=*.java'],
            capture_output=True,
            timeout=5,
            cwd='.',
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> int:
    """Extract symbols and generate a verified facts entry."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--diff', required=True, help='The PR diff text')
    args = parser.parse_args()

    symbols = extract_symbols_from_diff(args.diff)
    if not symbols:
        print("")
        return 0

    # Verify each symbol exists in the codebase
    verified = []
    for symbol in sorted(symbols):
        if verify_symbol_exists(symbol):
            verified.append(f"`{symbol}`")
            # Limit output to top 5 verified symbols to avoid excessive facts
            if len(verified) >= 5:
                break

    if verified:
        facts = "**Classes/methods confirmed present in codebase:** " + ", ".join(verified) + "."
        print(facts)
    else:
        print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
