from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: anydoc_worker INPUT.pdf OUTPUT.md", file=sys.stderr)
        return 2
    try:
        import anydoc

        markdown = anydoc.to_markdown(sys.argv[1])
        Path(sys.argv[2]).write_text(markdown, encoding="utf-8", newline="\n")
        return 0
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

