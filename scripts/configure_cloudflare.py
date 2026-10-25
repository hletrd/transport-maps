#!/usr/bin/env python3
"""Configure the worldmap proxy and scoped cache rules using a token file."""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4/"
HOST = "worldmap.atik.kr"


def configure(token: str, zone: str, rules_file: Path, backup: Path, *, apply: bool) -> None:
    def request(path, method="GET", body=None, *, missing=False):
        req = urllib.request.Request(API + f"zones/{zone}/" + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise RuntimeError(f"Cloudflare {method} {path}: {exc.code} {exc.read().decode()}") from None
        if not payload.get("success"):
            raise RuntimeError(f"Cloudflare {method} {path}: {payload.get('errors')}")
        return payload["result"]

    phase = "rulesets/phases/http_request_cache_settings/entrypoint"
    before = {"http3": request("settings/http3"), "ssl": request("settings/ssl"),
              "dns": request(f"dns_records?name={HOST}"), "cache": request(phase, missing=True)}
    if before["ssl"]["value"] not in ("full", "strict"):
        raise ValueError("the zone must already use encrypted origin connections (Full or Strict)")
    records = [r for r in before["dns"] if r["type"] in ("A", "AAAA", "CNAME") and r["proxiable"]]
    if not records:
        raise ValueError("no existing proxyable worldmap DNS record; refusing to invent one")
    wanted = json.loads(rules_file.read_text())["rules"]
    refs = {r["ref"] for r in wanted}
    keep = []
    allowed = {"id", "ref", "action", "action_parameters", "expression", "description", "enabled", "logging"}
    for rule in (before["cache"] or {}).get("rules", []):
        if rule.get("ref") not in refs:
            keep.append({k: v for k, v in rule.items() if k in allowed})
    if not apply:
        print(json.dumps({"host": HOST, "http3": before["http3"]["value"],
                          "ssl": before["ssl"]["value"], "proxy": [r["proxied"] for r in records],
                          "preservedRules": len(keep), "managedRules": wanted}))
        return
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(before, stream, indent=2)
    result = request(phase, "PUT", {"rules": keep + wanted})
    if before["http3"]["value"] != "on":
        request("settings/http3", "PATCH", {"value": "on"})
    for record in records:
        if not record["proxied"]:
            request(f"dns_records/{record['id']}", "PATCH", {"proxied": True})
    print(json.dumps({"host": HOST, "http3": "on", "proxied": True,
                      "ruleset": result["id"], "rules": len(result["rules"]), "backup": str(backup)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--zone-id", required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=Path(__file__).resolve().parents[1] / "deploy/cloudflare-cache-rules.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    configure(args.token_file.read_text().strip(), args.zone_id, args.rules, args.backup, apply=args.apply)
