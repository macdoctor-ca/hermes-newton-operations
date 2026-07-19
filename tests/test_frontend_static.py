"""Static contract and security tests for the Newton Operations dashboard."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = PLUGIN_ROOT / "dashboard"
MANIFEST = DASHBOARD / "manifest.json"
JAVASCRIPT = DASHBOARD / "dist" / "index.js"
STYLESHEET = DASHBOARD / "dist" / "style.css"
API_PREFIX = "/api/plugins/newton-operations"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dashboard_manifest_contract() -> None:
    manifest = json.loads(_read(MANIFEST))

    assert manifest["name"] == "newton-operations"
    assert manifest["label"] == "Operations"
    assert manifest["tab"]["path"] == "/operations"
    assert manifest["entry"] == "dist/index.js"
    assert manifest["css"] == "dist/style.css"
    assert manifest["api"] == "plugin_api.py"


def test_javascript_parses_with_node() -> None:
    node = shutil.which("node")
    assert node, "node is required for dashboard static verification"

    result = subprocess.run(
        [node, "--check", str(JAVASCRIPT)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_dashboard_uses_current_host_runtime_contract() -> None:
    source = _read(JAVASCRIPT)

    assert source.lstrip().startswith("(function () {")
    assert "window.__HERMES_PLUGIN_SDK__" in source
    assert "window.__HERMES_PLUGINS__" in source
    assert "React.createElement" in source
    assert 'register("newton-operations", NewtonOperationsPage)' in source
    assert f'const API = "{API_PREFIX}"' in source
    assert "SDK.fetchJSON" in source


def test_polling_and_refresh_lifecycle_are_explicit() -> None:
    source = _read(JAVASCRIPT)

    assert "setInterval" in source
    assert "clearInterval" in source
    assert re.search(r"setInterval\s*\([^,]+,\s*15000\s*\)", source)
    assert "Manual refresh" in source


def test_plugin_uses_host_page_landmarks_without_nested_main() -> None:
    source = _read(JAVASCRIPT)

    assert 'role: "region", "aria-label": "Newton Operations"' in source
    assert 'h("h2", null, "Newton Operations")' in source
    assert 'h("h1", null, "Newton Operations")' not in source


def test_required_operations_surfaces_and_actions_are_present() -> None:
    source = _read(JAVASCRIPT)

    for label in (
        "Gateway health",
        "Current work",
        "Needs attention",
        "Recent sessions",
        "Cron schedule",
        "Kanban flow",
        "Delegations & processes",
        "Decision & outcome journal",
    ):
        assert label in source

    assert 'api("/snapshot")' in source
    assert 'api("/journal")' in source
    assert 'api("/journal", {' in source
    assert 'api("/journal/" + encodeURIComponent(recordId) + "/seal"' in source


def test_frontend_does_not_bypass_host_auth_or_inject_markup() -> None:
    source = _read(JAVASCRIPT)

    forbidden = (
        "__HERMES_SESSION_TOKEN__",
        "dangerouslySetInnerHTML",
        ".innerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "localStorage",
        "sessionStorage",
    )
    for token in forbidden:
        assert token not in source

    assert not re.search(r"(?<![.\w])fetch\s*\(", source)
    assert not re.search(r"\b(?:https?|wss?)://", source, re.IGNORECASE)


def test_frontend_calls_only_its_scoped_api_namespace() -> None:
    source = _read(JAVASCRIPT)
    literal_api_paths = re.findall(r'(["\'])(/api/[^"\']+)\1', source)

    assert literal_api_paths
    assert all(path.startswith(API_PREFIX) for _, path in literal_api_paths)


def test_styles_are_theme_driven_and_responsive() -> None:
    css = _read(STYLESHEET)

    assert "var(--color-" in css
    assert "@media" in css
    assert "prefers-reduced-motion" in css
    assert not re.search(r"#[0-9a-f]{3,8}\b", css, re.IGNORECASE)
    assert not re.search(r"\brgba?\s*\(", css, re.IGNORECASE)
    assert not re.search(r"\bhsla?\s*\(", css, re.IGNORECASE)
    assert not re.search(r"\b(?:black|white)\b", css, re.IGNORECASE)
