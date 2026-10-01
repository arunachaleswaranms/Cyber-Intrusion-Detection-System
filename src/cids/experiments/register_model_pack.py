"""Register trusted local v2.0 final artifacts as an app-controlled model pack.

The source files are checked against the selected-artifact digests in the
accepted v2.1 gate evidence and copied, never deserialized. Registration does
not enable inference.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cids.workbench.model_pack import ModelPackError, describe_model_pack
from cids.workbench.registration import register_maintainer_final_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-artifact", required=True, type=Path)
    parser.add_argument("--multiclass-artifact", required=True, type=Path)
    parser.add_argument(
        "--pack-root",
        type=Path,
        default=None,
        help="defaults to artifacts/v2.1/model-packs in the repository",
    )
    parser.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        verified = register_maintainer_final_pack(
            args.binary_artifact,
            args.multiclass_artifact,
            confirmation=args.confirm,
            pack_root=args.pack_root,
        )
    except (ModelPackError, OSError) as exc:
        parser.exit(2, f"Model-pack registration: REFUSED\n{exc}\n")
    print("Model-pack registration: PASSED")
    for line in describe_model_pack(verified):
        print(line)
    print("Preflight: passed; no artifact was deserialized")
    print("Inference: not available until v2.1 Phase 3B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
