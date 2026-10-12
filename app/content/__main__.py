"""Export every page's original wording: `python -m app.content [--output FILE]`.

The website bundles this JSON (`frontend/src/content/site-content.json`) so each page can
still render if the API is unreachable while it builds or revalidates. Run it after
changing any page in `app/content/pages/`. It needs no database or settings.
"""

import argparse
import json
import sys
from pathlib import Path

from app.content import defaults


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.content", description=__doc__)
    parser.add_argument("--output", type=Path, help="file to write (default: standard output)")
    args = parser.parse_args()
    data = json.dumps(defaults(), indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(data)
    else:
        args.output.write_text(data, encoding="utf-8")
        sys.stderr.write(f"Wrote {args.output}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
