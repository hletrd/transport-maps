"""Keep existing zone rules and DNS targets when enabling the site's proxy."""

import io
import json
from pathlib import Path

import pytest

from scripts.configure_cloudflare import configure

RULES = Path(__file__).resolve().parents[1] / "deploy/cloudflare-cache-rules.json"


def api(monkeypatch, *, fail_cache=False):
    calls = []
    unrelated = {"id": "other", "ref": "other_site", "action": "set_cache_settings",
                 "expression": '(http.host eq "other.atik.kr")', "action_parameters": {"cache": False}}

    def urlopen(req, timeout):
        method = req.get_method()
        path = req.full_url.split("/zones/zone/")[1]
        body = json.loads(req.data) if req.data else None
        calls.append((method, path, body))
        if method == "GET":
            if path == "settings/http3":
                result = {"value": "on"}
            elif path == "settings/ssl":
                result = {"value": "full"}
            elif path.startswith("dns_records?"):
                result = [{"id": "record", "type": "A", "content": "192.0.2.1", "proxied": False, "proxiable": True}]
            else:
                result = {"id": "existing", "rules": [unrelated]}
        elif method == "PUT":
            if fail_cache:
                raise RuntimeError("cache API unavailable")
            result = {"id": "existing", "rules": body["rules"]}
        else:
            result = {"id": "record", "proxied": True}
        return io.BytesIO(json.dumps({"success": True, "result": result}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return calls, unrelated


def test_apply_preserves_other_rules_and_only_changes_dns_proxy_flag(monkeypatch, tmp_path):
    calls, unrelated = api(monkeypatch)
    backup = tmp_path / "before.json"
    configure("test-secret", "zone", RULES, backup, apply=True)
    mutations = [(m, p, b) for m, p, b in calls if m != "GET"]
    assert [m for m, _, _ in mutations] == ["PUT", "PATCH"]
    rules = mutations[0][2]["rules"]
    assert unrelated in rules
    assert all('http.host eq "worldmap.atik.kr"' in r["expression"] for r in rules if r is not rules[0])
    assert mutations[1] == ("PATCH", "dns_records/record", {"proxied": True})
    assert next(r for r in rules if r.get("ref") == "transport_maps_api")["action_parameters"]["cache"] is False
    assert "test-secret" not in backup.read_text()
    assert backup.stat().st_mode & 0o777 == 0o600


def test_failed_cache_configuration_does_not_switch_dns(monkeypatch, tmp_path):
    calls, _ = api(monkeypatch, fail_cache=True)
    with pytest.raises(RuntimeError, match="cache API"):
        configure("test-secret", "zone", RULES, tmp_path / "before.json", apply=True)
    assert not any(method == "PATCH" for method, _, _ in calls)


def test_preview_makes_no_changes_or_backup(monkeypatch, tmp_path):
    calls, _ = api(monkeypatch)
    backup = tmp_path / "before.json"
    configure("test-secret", "zone", RULES, backup, apply=False)
    assert all(method == "GET" for method, _, _ in calls)
    assert not backup.exists()


@pytest.mark.parametrize("path,ranged", [
    ("/data/build/water.pmtiles", True),
    ("/data/build/origins/seoul.r6.bin", True),
    ("/data/build/v/no-air/origins/seoul.over.bin", True),
    ("/data/build/hover_cells.bin", False),
    ("/data/build/origins/seoul.modes.bin", False),
    ("/data/build/origins/seoul.over.index.bin", False),
    ("/data/build/index.json", False),
    ("/api/solve", False),
])
def test_only_range_files_disable_origin_compression(path, ranged):
    rules = json.loads(RULES.read_text())["rules"]
    selected = []
    for rule in rules:
        if rule["action_parameters"].get("origin_range_requests", {}).get("mode") != "on":
            continue
        # This checked-in subset of the Rules language uses equality, boolean
        # operators and these two string predicates. Evaluate its real selectors.
        expression = rule["expression"].replace("http.host", "host").replace("http.request.uri.path", "path").replace(" eq ", " == ")
        selected.append(eval(expression, {"__builtins__": {}}, {"host": "worldmap.atik.kr", "path": path,
                        "starts_with": str.startswith, "ends_with": str.endswith}))
    assert any(selected) is ranged
