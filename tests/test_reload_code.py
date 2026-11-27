"""sextant.reload_code: dropping the loaded modules makes the next import read the disk."""
import importlib
import sys
import types

import sextant


def test_forget_code_makes_the_next_import_read_the_disk(tmp_path, monkeypatch):
    pkg = tmp_path / "reloadme"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .sub import VALUE\n")
    (pkg / "sub.py").write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # same-second edits must not hit a stale .pyc
    assert importlib.import_module("reloadme").VALUE == 1
    other = sys.modules.setdefault("reloadme_other", types.ModuleType("reloadme_other"))
    hass = types.SimpleNamespace(data={
        "components": {"reloadme": object(), "reloadme.sensor": object(), "reloadme_other": object()},
        "missing_platforms": {"reloadme.switch": True},
    })

    (pkg / "sub.py").write_text("VALUE = 2\n")
    importlib.invalidate_caches()
    assert importlib.import_module("reloadme").VALUE == 1  # still the loaded copy
    sextant._forget_code(hass, "reloadme", "reloadme")

    assert importlib.import_module("reloadme").VALUE == 2
    assert hass.data == {"components": {"reloadme_other": hass.data["components"]["reloadme_other"]}, "missing_platforms": {}}
    assert sys.modules.pop("reloadme_other") is other  # a name that only starts the same is left alone



def test_setup_clears_only_the_running_versions_marketplace_repair(monkeypatch):
    monkeypatch.setattr(sextant, "_CODE_VERSION", "2026.11.27.2")
    issue = lambda domain: types.SimpleNamespace(issue_domain=domain)  # noqa: E731
    hass = types.SimpleNamespace(data={"issues": {
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.2"): issue("sextant"),
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.3"): issue("sextant"),  # downloaded later
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.12"): issue("sextant"),
        ("marketplace", "restart_required_1365808237_tags/2026.11.27.2"): issue("ssh"),
        ("marketplace", "critical_tags/2026.11.27.2"): issue("sextant"),
        ("sextant", "restart_required_tags/2026.11.27.2"): issue("sextant"),
    }})
    sextant._clear_marketplace_restart(hass)
    assert ("marketplace", "restart_required_1366403240_tags/2026.11.27.2") not in hass.data["issues"]
    assert len(hass.data["issues"]) == 5


def test_code_version_is_the_manifests():
    import json
    from pathlib import Path
    manifest = Path(sextant.__file__).parent / "manifest.json"
    assert sextant._CODE_VERSION == json.loads(manifest.read_text())["version"]
