"""Preflight a registered model pack without deserializing either artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from cids.workbench.model_pack import (
    ModelPackError,
    describe_model_pack,
    preflight_model_pack,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        verified = preflight_model_pack(args.pack_dir)
    except (ModelPackError, OSError) as exc:
        parser.exit(2, f"Model-pack preflight: FAILED\n{exc}\n")
    print("Model-pack preflight: PASSED")
    for line in describe_model_pack(verified):
        print(line)
    print("No artifact was deserialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
