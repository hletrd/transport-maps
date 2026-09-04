import json
from typing import ClassVar

import numpy as np

from transport_maps import config
from transport_maps.emit import index


class FakeIndex:
    cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_hover_cell_ids_are_sorted_ascending(tmp_path):
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(FakeIndex(), out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) > 0
    assert (np.diff(ids.astype(object)) > 0).all()


# --- Attribution (C2) --------------------------------------------------------
#
# The licence firewall proves only that no commercial flight records leaked
# into dist/. It says nothing about crediting the open sources that legitimately
# did, so without these tests every gate reports green while the CC-BY-SA and
# ODbL redistribution obligations go unmet.

REQUIRED_ATTRIBUTION = {
    "Wikipedia": "CC BY-SA",
    "OpenStreetMap": "ODbL",
    "GRIP4": None,
    "OurAirports": None,
    "Natural Earth": None,
}


def _written_index(tmp_path) -> dict:
    out = tmp_path / "index.json"
    index.write_index(
        [{"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.9780}], out
    )
    return json.loads(out.read_text(encoding="utf-8"))


def test_index_json_attributes_every_required_source(tmp_path):
    payload = _written_index(tmp_path)
    assert payload["attribution"], "index.json ships no attribution at all"

    by_name = {entry["name"]: entry for entry in payload["attribution"]}
    for required, licence_fragment in REQUIRED_ATTRIBUTION.items():
        match = next((v for k, v in by_name.items() if required in k), None)
        assert match is not None, f"index.json does not attribute {required}"
        assert match["licence"].strip(), f"{required} has an empty licence"
        assert match["url"].strip(), f"{required} has no url"
        if licence_fragment is not None:
            assert licence_fragment in match["licence"], (
                f"{required} must ship under {licence_fragment}, got {match['licence']!r}"
            )


def test_attribution_entries_are_complete_records(tmp_path):
    """Every entry must carry all four fields, so a half-filled row cannot pass
    the per-source lookup above by name alone.
    """
    payload = _written_index(tmp_path)
    for entry in payload["attribution"]:
        assert set(entry) == {"name", "licence", "url", "usedFor"}
        assert all(str(v).strip() for v in entry.values())


def test_readme_documents_the_same_sources():
    """The obligation is on the artifact AND on the repo that produces it, and
    the two lists must not drift apart.
    """
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    for entry in index.ATTRIBUTION:
        assert entry["name"] in readme, f"README.md does not credit {entry['name']}"
        assert entry["licence"] in readme, f"README.md omits {entry['name']}'s licence"
