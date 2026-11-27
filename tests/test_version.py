"""The frontend's version file must match the manifest: the page reads its version from it."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "custom_components" / "sextant"


def test_frontend_version_file_matches_the_manifest():
    manifest = json.loads((ROOT / "manifest.json").read_text())["version"]
    js = (ROOT / "frontend" / "sextant-version.js").read_text()
    assert re.search(r'export const VERSION = "([^"]+)";', js).group(1) == manifest


def test_code_signature_is_stable_and_follows_the_sources(tmp_path, monkeypatch):
    from sextant import ws
    a = ws.code_signature()
    assert a and a == ws.code_signature()
    # A copy of the package: a source edit changes the first half, a requirement pin the second, a version bump neither.
    for p in [*ROOT.glob("*.py"), ROOT / "manifest.json"]:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(ws, "__file__", str(tmp_path / "ws.py"))
    monkeypatch.setattr(ws, "_signature_cache", [None, None])
    base = ws.code_signature()
    assert base == a
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "version": "9999.1.1.1"}))
    assert ws.code_signature() == base
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "requirements": [*manifest["requirements"], "extra==1"]}))
    moved = ws.code_signature()
    assert moved.split("|")[0] == base.split("|")[0] and moved.split("|")[1] != base.split("|")[1]
    (tmp_path / "ws.py").write_text((tmp_path / "ws.py").read_text() + "\n# edit\n")
    assert ws.code_signature().split("|")[0] != base.split("|")[0]
