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


def test_reload_clears_only_marketplaces_sextant_restart_repairs():
    issue = lambda domain: types.SimpleNamespace(issue_domain=domain)  # noqa: E731
    hass = types.SimpleNamespace(data={"issues": {
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.2"): issue("sextant"),
        ("marketplace", "restart_required_1365808237_tags/2026.11.26.01"): issue("ssh"),
        ("marketplace", "critical_x"): issue("sextant"),
        ("sextant", "restart_required_x"): issue("sextant"),
    }})
    sextant._clear_marketplace_restart(hass)
    assert set(hass.data["issues"]) == {
        ("marketplace", "restart_required_1365808237_tags/2026.11.26.01"),
        ("marketplace", "critical_x"),
        ("sextant", "restart_required_x"),
    }
