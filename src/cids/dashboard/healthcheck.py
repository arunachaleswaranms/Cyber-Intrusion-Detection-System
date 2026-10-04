"""Bounded local Streamlit health probe using only the standard library."""
from urllib.request import ProxyHandler, build_opener


def healthy() -> bool:
    try:
        # Ignore proxy environment settings for the container-local probe.
        with build_opener(ProxyHandler({})).open(
            "http://127.0.0.1:8501/_stcore/health", timeout=3
        ) as response:
            return response.status == 200 and response.read(16).strip() == b"ok"
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
