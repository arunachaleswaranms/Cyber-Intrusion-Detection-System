"""Real permission failures under non-root execution; synthetic test anchors only."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from cids.workbench.analysis import AnalysisUnavailable, preflight_binding
from cids.workbench import explanation_resources as er
from test_explanation_resources import resource_fixture
from test_workbench_model_pack import anchored_fake_artifacts, pinned_host_runtime, valid_pack

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="permission failures require non-root execution")


@pytest.mark.parametrize("filename", ["manifest.json", "binary.joblib"])
def test_unreadable_pack_has_safe_availability_failure(tmp_path, anchored_fake_artifacts, pinned_host_runtime, filename):
    directory, manifest = valid_pack(tmp_path)
    target = tmp_path / "artifacts/v2.1/model-packs" / directory.name
    target.parent.mkdir(parents=True)
    directory.rename(target)
    assert preflight_binding(tmp_path, directory.name).manifest == manifest
    private = target / filename
    original_mode = private.stat().st_mode
    private.chmod(0)
    try:
        with pytest.raises(AnalysisUnavailable) as caught:
            preflight_binding(tmp_path, directory.name)
        assert "failed verification" in str(caught.value)
        assert str(tmp_path) not in str(caught.value)
    finally:
        private.chmod(original_mode)


@pytest.mark.parametrize("filename", ["manifest.json", "binary-background.csv"])
def test_unreadable_resources_have_safe_failure(resource_fixture, filename):
    f = resource_fixture
    assert er.load_resources(f.repo, f.root.name, f.pack).resource_id == f.root.name
    private = f.root / filename
    original_mode = private.stat().st_mode
    private.chmod(0)
    try:
        with pytest.raises(er.ResourceError) as caught:
            er.load_resources(f.repo, f.root.name, f.pack)
        assert "unavailable or invalid" in str(caught.value)
        assert str(f.repo) not in str(caught.value)
    finally:
        private.chmod(original_mode)
