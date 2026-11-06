"""Explicit exact-item context using the deployment's existing tracker selection."""
from __future__ import annotations

import argparse

from .deployment import command_environment, resolve_root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root")
    parser.add_argument("item")
    args = parser.parse_args(argv)
    args.root, how = resolve_root(args.root)
    # Reuse selection and proof; never choose a fallback store for this reader.
    from .cli import _raw_tracker
    from .quipu import resolve_onto
    from .work_context import context, render
    try:
        with command_environment(args.root, how):
            tracker = _raw_tracker(args)
            print(render(context(tracker, args.item,
                                 onto=resolve_onto(root=args.root), timeout=3)))
    except Exception as exc:
        print(f"exact context UNKNOWN ({type(exc).__name__}); not an empty answer")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
