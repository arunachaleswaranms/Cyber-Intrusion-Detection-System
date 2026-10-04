# Verified official multi-platform index; see docs/container.md.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    HOME=/tmp/cids-home XDG_CACHE_HOME=/tmp/cids-cache NUMBA_CACHE_DIR=/tmp/cids-numba \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements-container.txt requirements-dashboard.txt requirements-workbench.txt requirements-reproduction.txt ./
RUN python -m pip install --no-cache-dir pip==26.2.1 \
    && python -m pip install --no-cache-dir -r requirements-container.txt \
    && python -m pip check \
    && groupadd --gid 10001 cids \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/cids-home cids
COPY src/cids/ src/cids/
COPY dashboard/ dashboard/
COPY .streamlit/config.toml .streamlit/config.toml
COPY configs/ configs/
COPY results/ results/
COPY dataset/unsw-nb15/manifest.json dataset/unsw-nb15/manifest.json
COPY samples/ samples/
COPY docs/ docs/
COPY README.md LICENSE PROJECT_PLAN.md ./
RUN mkdir -p artifacts/v2.1/model-packs artifacts/v2.1/explanation-resources \
    && chmod -R go-w /app
USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "cids.dashboard.healthcheck"]
CMD ["python", "-m", "cids.dashboard.container"]
