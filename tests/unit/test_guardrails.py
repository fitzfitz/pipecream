"""Static checks for the AGENTS.md hard guardrails (memory isolation + container boundary)."""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEAVY_MODULES = {"mlx", "mlx_lm", "mlx_whisper", "mflux", "kokoro_onnx"}


def _imported_roots(nodes):
    roots = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("filename", ["orchestrator.py", "dashboard.py", "db.py"])
def test_control_plane_never_imports_heavy_modules(filename):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    assert not (_imported_roots(ast.walk(tree)) & HEAVY_MODULES)


@pytest.mark.parametrize("filename", sorted(p.name for p in (ROOT / "workers").glob("step*.py")))
def test_workers_defer_heavy_imports(filename):
    """Top-level heavy imports would break DRY_RUN_AI=1 and unit-test imports."""
    tree = ast.parse((ROOT / "workers" / filename).read_text(encoding="utf-8"))
    assert not (_imported_roots(tree.body) & HEAVY_MODULES)


@pytest.mark.parametrize("filename", ["step1_topic_script.py", "step2_audio_subs.py", "step3_images.py"])
def test_ai_workers_honour_dry_run_flag(filename):
    assert 'os.environ.get("DRY_RUN_AI") == "1"' in (ROOT / "workers" / filename).read_text(encoding="utf-8")


def test_docker_requirements_are_lightweight():
    reqs = (ROOT / "requirements-docker.txt").read_text(encoding="utf-8").lower()
    for pkg in ("mlx", "mflux", "kokoro"):
        assert pkg not in reqs


def test_dashboard_image_does_not_install_mac_requirements():
    dockerfile = (ROOT / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert "requirements-mac" not in dockerfile
    assert "requirements-docker.txt" in dockerfile


def test_compose_bind_mounts_keep_z_suffix():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    mounts = re.findall(r"^\s*-\s*(\./[^\s]+)\s*$", compose, re.MULTILINE)
    assert mounts, "expected bind mounts in compose.yaml"
    assert all(m.endswith(":Z") for m in mounts), mounts
