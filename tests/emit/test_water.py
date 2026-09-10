"""The water tileset's zoom range against the zoom range the page can request.

This module had no tests: water.pmtiles is one of the four REQUIRED_EXTRAS
whose only verification was that the file exists.

MapLibre asks a vector source for floor(mapZoom), and web/app.js caps the map
at maxZoom 11, so every tile the emitter builds above that is bytes nobody can
fetch. Decoding the shipped archive found 366,690,691 of its 858 MB tile
section -- 42.7% -- referenced only at z >= 12.
"""

import re

from transport_maps import config
from transport_maps.emit import water

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _page_max_zoom() -> int:
    m = re.search(r"maxZoom:\s*(\d+)", APP)
    assert m, "web/app.js no longer sets maxZoom on the Map"
    return int(m.group(1))


def test_the_tileset_is_not_built_above_the_zoom_the_page_can_ask_for():
    """Emitter-max <= page-max, deliberately NOT equality.

    An equality gate would have passed on 12 == 12 -- which is the state that
    put 366 MB of unfetchable tiles in the archive -- and would also fire
    spuriously if the page were ever capped BELOW a tileset that is merely
    generous. The direction is what matters.
    """
    page = _page_max_zoom()
    assert water.MAX_ZOOM <= page, (
        f"water.pmtiles is built to z{water.MAX_ZOOM} but the page can never request "
        f"above z{page}: every tile above that is bytes nobody can fetch")


def test_the_tileset_covers_every_zoom_the_page_can_ask_for():
    """The other direction: a cap set too low leaves the coast a hex edge at
    the zooms a visitor actually reads at."""
    assert water.MIN_ZOOM == 0, "the opening view is below z1"
    assert water.MAX_ZOOM >= _page_max_zoom(), (
        f"the page reaches z{_page_max_zoom()} and the tileset stops at z{water.MAX_ZOOM}")


def test_the_lake_filter_thresholds_are_monotonic_in_zoom():
    """Smaller lakes appear as you zoom in, never the reverse -- otherwise a
    lake visible at z5 vanishes at z7."""
    pairs = re.findall(r'\[">=", "\$zoom", (\d+)\], \[">=", "Lake_area", ([\d.]+)\]',
                       water.LAKE_ZOOM_FILTER)
    assert len(pairs) >= 4, water.LAKE_ZOOM_FILTER
    zooms = [int(z) for z, _ in pairs]
    areas = [float(a) for _, a in pairs]
    assert zooms == sorted(zooms), zooms
    assert areas == sorted(areas, reverse=True), areas


def test_the_simplification_stays_under_a_pixel_at_the_page_maximum():
    """SIMPLIFICATION is in tile-space units at MAX_ZOOM."""
    # One tile-space unit at zoom z, in metres: 40,075,016.686 / (2**z * 4096).
    unit_m = 40_075_016.686 / (2 ** water.MAX_ZOOM * 4096)
    px_m = 40_075_016.686 / (512 * 2 ** _page_max_zoom())
    assert water.SIMPLIFICATION * unit_m < px_m, (
        f"{water.SIMPLIFICATION * unit_m:.1f} m of simplification against a {px_m:.1f} m pixel")
