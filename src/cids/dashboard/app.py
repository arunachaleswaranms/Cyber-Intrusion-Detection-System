"""Compose the evidence dashboard pages and shared chrome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from cids.dashboard.components import (
    STATUS_ICONS,
    STATUS_LABELS,
    health_badge,
    research_notice,
)
from cids.dashboard.views import (
    binary,
    explainability,
    families,
    overview,
    provenance,
)
from cids.workbench.catalog import REPO_ROOT, EvidenceCatalog, load_catalog
from cids.workbench.integrity import EvidenceError

LOOPBACK_ADDRESSES = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    icon: str
    section: str
    render: Callable[[EvidenceCatalog], None]


PAGES = (
    PageSpec(
        "overview", "Overview", ":material/dashboard:", "Results", overview.render
    ),
    PageSpec(
        "binary", "Binary detection", ":material/security:", "Results", binary.render
    ),
    PageSpec(
        "families", "Attack families", ":material/category:", "Results", families.render
    ),
    PageSpec(
        "explainability",
        "Explainability",
        ":material/psychology_alt:",
        "Method",
        explainability.render,
    ),
    PageSpec(
        "provenance",
        "Evidence & provenance",
        ":material/fact_check:",
        "Method",
        provenance.render,
    ),
)
PAGE_KEYS = tuple(page.key for page in PAGES)


def _sidebar(catalog: EvidenceCatalog) -> None:
    with st.sidebar:
        st.markdown("### Evidence health")
        health_badge(catalog)
        for component in catalog.components:
            st.caption(
                f"{STATUS_ICONS[component.status]} {component.title}:"
                f" {STATUS_LABELS[component.status].lower()}"
            )
        st.divider()
        st.caption(
            "Evidence mode reads committed JSON only. It does not load model "
            "artifacts, read the dataset, or make predictions."
        )


def exposure_problems(address: object, gather_usage_stats: object) -> list[str]:
    """Explain why the running server violates the local-only policy, if it does.

    ``.streamlit/config.toml`` only applies when Streamlit starts in the
    repository root, so the policy is re-checked at runtime and fails closed.
    """
    problems = []
    if address not in LOOPBACK_ADDRESSES:
        shown = address if address else "all interfaces (unset)"
        problems.append(f"the server listens on {shown}, not loopback")
    if gather_usage_stats is not False:
        problems.append("Streamlit usage telemetry is enabled")
    return problems


def _enforce_local_only() -> None:
    problems = exposure_problems(
        st.get_option("server.address"), st.get_option("browser.gatherUsageStats")
    )
    if problems:
        st.error(
            "**Refusing to render: " + "; ".join(problems) + ".** Start the "
            "dashboard from the repository root so `.streamlit/config.toml` "
            "applies, or pass `--server.address 127.0.0.1 "
            "--browser.gatherUsageStats false`.",
            icon=":material/lock:",
        )
        st.stop()


def _render_guarded(spec: PageSpec, catalog: EvidenceCatalog) -> None:
    """Show evidence contract violations on the page; let code defects raise."""
    try:
        spec.render(catalog)
    except EvidenceError as exc:
        st.error(
            "**This page stopped because verified evidence violated a display "
            f"contract.** {exc}. Nothing after this point was rendered, and no "
            "substitute values were used.",
            icon=":material/gpp_bad:",
        )


def _configure() -> None:
    st.set_page_config(
        page_title="CIDS v2.1 evidence dashboard",
        page_icon=":material/shield:",
        layout="wide",
    )


def _page_callable(spec: PageSpec, catalog: EvidenceCatalog) -> Callable[[], None]:
    def page() -> None:
        _render_guarded(spec, catalog)

    page.__name__ = f"page_{spec.key}"
    return page


def main(repo_root: str | Path = REPO_ROOT) -> None:
    """Render the multipage dashboard. Evidence is re-verified on every run."""
    _configure()
    _enforce_local_only()
    catalog = load_catalog(repo_root)
    sections: dict[str, list] = {}
    for spec in PAGES:
        sections.setdefault(spec.section, []).append(
            st.Page(
                _page_callable(spec, catalog),
                title=spec.title,
                icon=spec.icon,
                # The default page is served at "/", so it takes no URL path.
                url_path=None if spec.key == "overview" else spec.key,
                default=spec.key == "overview",
            )
        )
    navigation = st.navigation(sections)
    _sidebar(catalog)
    research_notice()
    navigation.run()


def render_single_page(key: str, repo_root: str | Path = REPO_ROOT) -> None:
    """Render one page without navigation; used by the Streamlit test harness."""
    specs = {spec.key: spec for spec in PAGES}
    if key not in specs:
        raise ValueError(f"unknown dashboard page: {key!r}")
    _configure()
    catalog = load_catalog(repo_root)
    _sidebar(catalog)
    research_notice()
    _render_guarded(specs[key], catalog)
