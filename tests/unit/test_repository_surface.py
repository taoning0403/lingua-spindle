from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"!?(?:\[[^]]*\])\(([^)]+)\)")


def test_required_open_source_and_deployment_surface_exists() -> None:
    required = {
        "LICENSE",
        "README.md",
        "README.zh-CN.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "CHANGELOG.md",
        ".env.example",
        ".dockerignore",
        "Dockerfile",
        "compose.yaml",
        "third-party-components.toml",
        "acceptance/README.md",
        "acceptance/v0.1.0/README.md",
        "acceptance/v0.1.0/reports/acceptance-report.md",
        "acceptance/v0.1.0/reports/supplemental-docker-wsl-report.md",
        "acceptance/v0.1.0/evidence/command-log.txt",
        "docs/architecture.md",
        "docs/data-model.md",
        "docs/installation.md",
        "docs/docker.md",
        "docs/api.md",
        "docs/adapter-development.md",
    }
    assert {item for item in required if not (ROOT / item).is_file()} == set()
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("Apache License")


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    for document in ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in document.relative_to(ROOT).parts):
            continue
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_text = target.split("#", maxsplit=1)[0]
            if path_text and not (document.parent / path_text).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert missing == []


def test_structured_third_party_inventory_has_required_fields() -> None:
    with (ROOT / "third-party-components.toml").open("rb") as handle:
        inventory = tomllib.load(handle)
    required = {
        "name",
        "upstream",
        "version",
        "license",
        "integration",
        "modified",
        "model_weights",
        "fonts",
        "redistributed",
    }
    components = inventory["component"]
    assert len(components) >= 10
    assert all(required <= set(component) for component in components)
    manga = next(item for item in components if item["name"] == "manga-image-translator")
    assert manga["license"] == "GPL-3.0-only"
    assert manga["redistributed"] is False
    assert "operator-managed external HTTP service" in manga["integration"]


def test_container_defaults_are_non_root_and_host_loopback_only() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "USER 10001:10001" in dockerfile
    assert 'VOLUME ["/data"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert '"127.0.0.1:${LINGUASPINDLE_PORT:-8765}:8765"' in compose
    assert "linguaspindle-data:/data" in compose
    assert "no-new-privileges:true" in compose
    assert "LINGUASPINDLE_OPENAI_TIMEOUT_SECONDS" in compose
    assert "LINGUASPINDLE_OPENAI_CONCURRENCY" in compose
    assert "LINGUASPINDLE_OPENAI_MAX_RETRIES" in compose
