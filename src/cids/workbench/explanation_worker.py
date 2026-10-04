"""Standalone process entry: bounded stdin/stdout, independent of Streamlit."""
import sys
from cids.workbench.explanation_service import MAX_REQUEST_BYTES, worker_result


def main():
    request = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    response = worker_result(request)
    sys.stdout.buffer.write(response)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
