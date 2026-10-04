"""Standalone synthetic child fixtures. Never imported by production services."""
import json
import os
import sys
import time
from pathlib import Path


def main():
    mode = sys.argv[1]
    if mode == "sleep":
        time.sleep(30)
    elif mode == "error":
        sys.stdout.buffer.write(b'{"status":"failed"}')
    elif mode == "oversized":
        sys.stdout.buffer.write(b"x" * (128 * 1024 + 1))
    elif mode == "partial":
        sys.stdout.buffer.write(b'{"status":')
        sys.stdout.buffer.flush()
        time.sleep(30)
    elif mode == "exit":
        os._exit(7)
    elif mode == "representative":
        from cids.workbench import model_pack
        from cids.workbench.analysis import configured_pack_dir
        from cids.workbench.explanation_service import MAX_REQUEST_BYTES, worker_result
        request = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        req = json.loads(request)
        directory = configured_pack_dir(Path(req["repo_root"]), req["model_pack_id"])
        manifest = json.loads((directory / "manifest.json").read_text())
        # Explicit test-only synthetic anchor; verified loader still runs in full.
        model_pack.load_maintainer_final_digests = lambda *_: {t: spec["sha256"] for t, spec in manifest["artifacts"].items()}
        sys.stdout.buffer.write(worker_result(request))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
