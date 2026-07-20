"""Release metadata and workflow immutability contracts."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_github_actions_are_pinned_to_commit_shas() -> None:
    workflow_files = sorted(WORKFLOWS.glob("*.yml"))
    assert workflow_files
    for path in workflow_files:
        source = path.read_text(encoding="utf-8")
        uses = re.findall(r"^\s*- uses:\s*([^\s#]+)", source, re.MULTILINE)
        assert uses, path
        for action in uses:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), (path, action)


def test_ci_tool_versions_are_immutable_and_dependabot_tracks_actions() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert 'version: "0.11.6"' in ci
    assert 'version: "latest"' not in ci
    assert "package-ecosystem: github-actions" in dependabot
