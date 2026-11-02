"""Release-repository consistency checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "ha_delonghi_coffeelink_eletta_explore"


def test_release_metadata_quality_scale_and_workflows_are_consistent() -> None:
    """Prevent stale release claims and floating third-party workflow code."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_cs = (ROOT / "docs" / "README_CS.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    audit = (ROOT / "docs" / "TECHNICAL_AUDIT.md").read_text(encoding="utf-8")
    hacs_link = (
        "https://my.home-assistant.io/redirect/hacs_repository/"
        "?owner=kasiom&repository=ha-delonghi-coffeelink-eletta-explore"
        "&category=integration"
    )

    assert manifest["version"] == "1.3.1"
    assert hacs["homeassistant"] == "2026.8.2"
    assert all(hacs_link in document for document in (readme, readme_cs, installation))
    assert "Private acceptance testing" not in readme
    assert "soukromé ověřování" not in readme_cs
    assert "private repository stage" not in installation.lower()
    assert "v1.1.26" not in readme_cs
    assert "pre-clean recovery bundle is retained" not in audit.lower()
    assert "pre-clean recovery bundle was permanently" in audit.lower()
    assert not (COMPONENT / "strings.json").exists()
    assert len([path for path in (ROOT / "custom_components").iterdir() if path.is_dir()]) == 1

    quality = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8"))["rules"]
    assert {
        "runtime-data",
        "parallel-updates",
        "dynamic-devices",
        "stale-devices",
        "repair-issues",
        "icon-translations",
        "test-coverage",
        "async-dependency",
        "inject-websession",
        "strict-typing",
    } <= quality.keys()

    pinned_action = re.compile(r"^\s*uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#.*)?$")
    uses_lines = [
        line
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("uses:")
    ]
    assert uses_lines
    assert all(pinned_action.fullmatch(line) for line in uses_lines)

    workflows = [workflow.read_text(encoding="utf-8") for workflow in (ROOT / ".github" / "workflows").glob("*.yml")]
    assert workflows
    assert all("  public:" in workflow for workflow in workflows)


def test_local_markdown_links_resolve() -> None:
    """Keep public documentation free of broken repository-local links."""
    markdown_link = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    missing: list[str] = []

    for document in ROOT.rglob("*.md"):
        if ".git" in document.parts:
            continue
        for raw_target in markdown_link.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = unquote(target.split("#", maxsplit=1)[0])
            if target and not (document.parent / target).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")

    assert not missing


def test_runtime_matrix_preserves_minimum_and_current_home_assistant() -> None:
    """A test dependency refresh must not silently drop the minimum HA runtime."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["home-assistant-runtime"]
    assert job["strategy"]["fail-fast"] is False
    environments = job["strategy"]["matrix"]["include"]
    minimum = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    assert {item["ha_version"] for item in environments} == {minimum, "2026.10.4"}
    assert sum(item["type_check"] for item in environments) == 1
    for item in environments:
        assert (ROOT / item["requirements"]).is_file()
        assert item["type_check"] is (item["ha_version"] != minimum)
