"""_entry.py — the shared __main__ dispatcher for kunglao-* entry scripts
(#585, limited first wave: the 8 entry scripts).

The dispatcher replaces ONLY the `if __name__ == "__main__": sys.exit(main())`
boilerplate. The #370 router contract is untouched: entry modules keep their
module-level main(argv) (or their sibling-module import) — run() calls it.

Usage in an entry script:

    from _entry import run
    run(globals())          # or run(globals(), main=my_main)

run() resolves `main` from the module globals unless passed explicitly.
"""
from __future__ import annotations

import sys


def run(module_globals: dict, main=None) -> None:
    """Execute main(argv=None) and sys.exit its return code.

    Never called at import time — entry scripts invoke it inside their
    `if __name__ == "__main__":` guard, keeping `python -c 'import mod'`
    side-effect free (the reason main(argv) exists, #370)."""
    fn = main or module_globals.get("main")
    if fn is None:
        print("_entry: no main() found in module", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(fn())
