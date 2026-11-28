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


def test_a_frontend_only_update_clears_every_sextant_restart_repair(monkeypatch):
    import asyncio

    from sextant import ws

    monkeypatch.setattr(sextant, "_CODE_VERSION", "2026.11.27.2")
    issue = lambda domain: types.SimpleNamespace(issue_domain=domain)  # noqa: E731
    issues = {
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.9"): issue("sextant"),
        ("marketplace", "restart_required_1366403240_tags/2026.11.27.10"): issue("sextant"),
        ("marketplace", "restart_required_1365808237_tags/2026.11.27.10"): issue("ssh"),
    }

    async def executor(fn, *args):
        return fn(*args)

    hass = types.SimpleNamespace(data={"issues": dict(issues)}, async_add_executor_job=executor)
    # The Python on disk differs from the running code: the repairs stay.
    monkeypatch.setattr(ws, "RUNNING_CODE", "old")
    monkeypatch.setattr(ws, "code_signature", lambda: "new")
    asyncio.run(sextant._clear_restart_if_same_code(hass))
    assert len(hass.data["issues"]) == 3
    # The same Python: only the frontend changed, so Sextant's go and the other integration's stays.
    monkeypatch.setattr(ws, "code_signature", lambda: "old")
    asyncio.run(sextant._clear_restart_if_same_code(hass))
    assert list(hass.data["issues"]) == [("marketplace", "restart_required_1365808237_tags/2026.11.27.10")]


def test_code_version_is_the_manifests():
    import json
    from pathlib import Path
    manifest = Path(sextant.__file__).parent / "manifest.json"
    assert sextant._CODE_VERSION == json.loads(manifest.read_text())["version"]


class _Entries:
    """Config entries that "set up" by importing the fake integration and calling its setup()."""

    def __init__(self, entries):
        self.entries = entries

    def async_entries(self, domain, **_kw):
        return self.entries

    def async_loaded_entries(self, domain):
        return [e for e in self.entries if e.state is sextant.ConfigEntryState.LOADED]

    async def async_unload(self, entry_id):
        for e in self.entries:
            e.state = sextant.ConfigEntryState.NOT_LOADED
        return True

    async def async_setup(self, entry_id):
        for e in self.entries:
            try:
                e.running = importlib.import_module("reloadme").setup()
                e.state = sextant.ConfigEntryState.LOADED
            except Exception:  # noqa: BLE001
                e.state = sextant.ConfigEntryState.SETUP_ERROR
        return all(e.state is sextant.ConfigEntryState.LOADED for e in self.entries)


def _reload_fixture(tmp_path, monkeypatch):
    """A fake integration "reloadme" that stands in for sextant, so the real files are never edited."""
    import asyncio

    pkg = tmp_path / "reloadme"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .sub import VALUE\n\n\ndef setup():\n    return VALUE\n")
    (pkg / "sub.py").write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sextant, "__name__", "reloadme")
    monkeypatch.setattr(sextant, "__file__", str(pkg / "__init__.py"))
    monkeypatch.setattr(sextant, "DOMAIN", "reloadme")
    monkeypatch.setattr(sextant, "_import_code", lambda package: importlib.import_module(package))
    monkeypatch.setattr(sextant.ir, "async_get", lambda hass: types.SimpleNamespace(issues={}), raising=False)
    monkeypatch.delitem(sys.modules, "reloadme", raising=False)
    monkeypatch.delitem(sys.modules, "reloadme.sub", raising=False)
    entry = types.SimpleNamespace(entry_id="x", title="Sextant", state=sextant.ConfigEntryState.NOT_LOADED, running=None)

    async def run(fn, *args):
        return fn(*args)

    hass = types.SimpleNamespace(data={"components": {}, "missing_platforms": {}}, config_entries=_Entries([entry]),
                                 async_add_executor_job=run, async_add_import_executor_job=run)
    asyncio.run(hass.config_entries.async_setup("x"))
    assert entry.running == 1
    old = sys.modules["reloadme"]

    def reload():
        asyncio.run(sextant._reload_code_once(hass))
        importlib.invalidate_caches()

    def write(name, text):
        (pkg / name).write_text(text)
        importlib.invalidate_caches()

    return hass, entry, old, reload, write


def test_a_syntax_error_unloads_nothing(tmp_path, monkeypatch):
    import pytest

    hass, entry, old, reload, write = _reload_fixture(tmp_path, monkeypatch)
    write("sub.py", "VALUE = (\n")
    with pytest.raises(Exception, match=r"sub\.py line 1.*unchanged"):
        reload()
    assert entry.state is sextant.ConfigEntryState.LOADED
    assert sys.modules["reloadme"] is old


def test_an_import_error_puts_the_previous_code_back(tmp_path, monkeypatch):
    import pytest

    hass, entry, old, reload, write = _reload_fixture(tmp_path, monkeypatch)
    write("sub.py", "VALUE = no_such_name\n")
    with pytest.raises(Exception, match="previous code is running again"):
        reload()
    assert entry.state is sextant.ConfigEntryState.LOADED
    assert entry.running == 1
    assert sys.modules["reloadme"] is old

    write("sub.py", "VALUE = 3\n")  # the action still works once the code is fixed
    reload()
    assert entry.state is sextant.ConfigEntryState.LOADED and entry.running == 3


def test_a_setup_error_puts_the_previous_code_back(tmp_path, monkeypatch):
    import pytest

    hass, entry, old, reload, write = _reload_fixture(tmp_path, monkeypatch)
    write("__init__.py", "from .sub import VALUE\n\n\ndef setup():\n    if VALUE != 1:\n        raise RuntimeError\n    return VALUE\n")
    write("sub.py", "VALUE = 2\n")
    with pytest.raises(Exception, match="did not set up.*previous code"):
        reload()
    assert entry.state is sextant.ConfigEntryState.LOADED
    assert entry.running == 1
    assert sys.modules["reloadme"] is old


def test_a_rollback_starts_the_old_code_from_clean_flags(tmp_path, monkeypatch):
    import pytest

    hass, entry, old, reload, write = _reload_fixture(tmp_path, monkeypatch)
    seen = []
    real_setup = hass.config_entries.async_setup

    async def setup(entry_id):
        seen.append(hass.data.get("sextant_initialized"))
        ok = await real_setup(entry_id)
        hass.data["sextant_initialized"] = True  # what the real setup sets before it can fail
        return ok

    hass.config_entries.async_setup = setup
    write("__init__.py", "from .sub import VALUE\n\n\ndef setup():\n    if VALUE != 1:\n        raise RuntimeError\n    return VALUE\n")
    write("sub.py", "VALUE = 2\n")
    with pytest.raises(Exception, match="previous code"):
        reload()
    assert seen == [None, None]  # the new setup, then the old one: neither saw a leftover flag
    assert entry.state is sextant.ConfigEntryState.LOADED and entry.running == 1


def test_a_rollback_with_nothing_loaded_says_there_is_no_previous_code(tmp_path, monkeypatch):
    import pytest

    hass, entry, old, reload, write = _reload_fixture(tmp_path, monkeypatch)
    entry.state = sextant.ConfigEntryState.NOT_LOADED
    write("sub.py", "VALUE = no_such_name\n")
    with pytest.raises(Exception, match="no previous code"):
        reload()
