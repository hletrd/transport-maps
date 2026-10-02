import re
from pathlib import Path

import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import routes, wikidata

FIXTURE = Path(__file__).parent.parent / "fixtures" / "icn_wikitext.txt"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "routes"


def test_parses_destination_article_titles_from_real_page():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    assert len(titles) > 50
    # Narita and Los Angeles are long-standing ICN destinations.
    assert any("Narita" in t for t in titles)
    assert any("Los_Angeles" in t or "Los Angeles" in t for t in titles)


def test_ignores_non_destination_links():
    # The real ICN fixture's section body happens to contain zero File:/
    # Category: links, so testing against it would pass even with
    # _SKIP_PREFIXES deleted entirely. Use a small inline wikitext string
    # that actually contains one, so the assertion proves the filter does
    # something.
    wikitext = (
        "== Airlines and destinations ==\n"
        "{{Airline destination list\n"
        "|[[Test Airlines]]|[[File:Some_icon.svg]] [[Category:Test airports]] "
        "[[Test Destination Airport]]\n"
        "}}\n"
    )
    titles = routes.parse_destinations(wikitext)
    assert "Test_Destination_Airport" in titles
    assert not any(t.startswith(("File:", "Category:", "Help:")) for t in titles)


def test_ignores_cargo_subsection():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    # ICN's Cargo subsection lists freight-only carriers that never appear
    # among its passenger destinations.
    assert "Cargolux" not in titles


def test_cargo_cut_does_not_discard_a_later_passenger_subsection():
    # Regression guard: an earlier version cut everything from the first
    # Cargo/Freight heading to the end of the section, which would also
    # silently discard a Passenger subsection that happens to follow Cargo
    # in the wikitext. Only the Cargo span itself must be removed.
    wikitext = (
        "== Airlines and destinations ==\n"
        "===Passenger===\n"
        "[[Alpha Airline]] [[Alpha Airport]]\n"
        "===Cargo===\n"
        "[[Cargo Only Co]] [[Cargo Destination Airport]]\n"
        "===More Passenger===\n"
        "[[Beta Airline]] [[Beta Airport]]\n"
        "== Ground transportation ==\n"
        "Some unrelated text.\n"
    )
    titles = routes.parse_destinations(wikitext)
    assert "Alpha_Airport" in titles
    assert "Beta_Airport" in titles
    assert "Cargo_Destination_Airport" not in titles


def test_a_level_3_section_stops_at_its_next_sibling():
    """CR13-2. Filed under "== Operations ==", the section is a level-3
    heading, and it used to run on to the next LEVEL-2 heading -- through the
    accident report and the traffic table after it, so an aircraft type and a
    crash's intended destination became scheduled routes.

    The fixture is constructed in the shape of such an article (no network in
    tests). Mutation, measured: closing the section at the next level-2
    heading again (the old `^==[^=]` cut) turns this red.
    """
    titles = routes.parse_destinations((FIXTURES / "level3_section.wikitext").read_text())
    assert titles == [
        "Air_Example", "Hub_International_Airport", "Coastal_Airport",
        "Island_Air", "Remote_Island_Airport",
    ]
    # Spelled out, because the list above is what a regression would change:
    for sibling in ("McDonnell_Douglas_DC-9", "Distant_City_Airport", "Busy_Hub_Airport"):
        assert sibling not in titles
    # A deeper Cargo subsection inside the level-3 section is still cut.
    assert "Cargo_Hub_Airport" not in titles


def test_a_level_2_section_keeps_its_own_subsections():
    """The other half: closing at "same level or shallower" must not close a
    level-2 section at its own level-3 Passenger heading."""
    wikitext = (
        "== Airlines and destinations ==\n"
        "=== Passenger ===\n"
        "[[Alpha Airport]]\n"
        "=== Seasonal ===\n"
        "[[Beta Airport]]\n"
        "== Statistics ==\n"
        "[[Gamma Airport]]\n"
    )
    assert routes.parse_destinations(wikitext) == ["Alpha_Airport", "Beta_Airport"]


def test_a_link_with_a_section_fragment_keeps_its_destination():
    """CR13-6. `[[Article#Section|label]]` used to match nothing: the title
    capture stops at "#", and the regex then demanded "|" or "]]". Three of
    the four destination airports below were silently dropped. The fragment is not
    part of the title Wikidata resolves, so it is cut, not kept.

    Mutation, measured: restoring the old `_LINK_RE` turns this red.
    """
    titles = routes.parse_destinations((FIXTURES / "fragment_links.wikitext").read_text())
    assert titles == [
        "Air_Example", "Hub_International_Airport", "Tokyo_International_Airport",
        "London_Heathrow_Airport", "Seasonal_Air", "Lake_Airport", "Example_Connect",
    ]
    # A same-page anchor names no article, and the link under "Ground
    # transport" is outside the section.
    assert "" not in titles and "Example_City" not in titles


@pytest.mark.network
def test_resolves_article_titles_to_iata_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    got = wikidata.iata_for_titles([
        "Narita International Airport",
        "Incheon International Airport",
        "Seoul",  # a city, not an airport -> must be absent
    ])
    assert got["Narita International Airport"] == "NRT"
    assert got["Incheon International Airport"] == "ICN"
    assert "Seoul" not in got


@pytest.mark.network
def test_resolves_underscore_titles_under_the_exact_key_passed_in(tmp_path, monkeypatch):
    # parse_destinations() always yields underscore-form titles (see its
    # ".replace(' ', '_')"). MediaWiki's `query.normalized` reports these
    # relative to the space-form title, so the resolver must map back to
    # the underscore form the caller actually asked for -- not silently
    # drop it. This is the exact bug class that once poisoned the whole
    # destination cache with empty results for real, resolvable airports.
    #
    # config.CACHE is redirected to an empty tmp_path so this test actually
    # exercises the resolver instead of reading an already-warm real cache
    # (which would pass even with the fix reverted).
    monkeypatch.setattr(config, "CACHE", tmp_path)
    got = wikidata.iata_for_titles(["Aalborg_Airport"])
    assert got["Aalborg_Airport"] == "AAL"


@pytest.mark.network
def test_resolves_both_titles_when_two_collapse_to_the_same_page(tmp_path, monkeypatch):
    # "Narita_Airport" redirects to the same article that "Narita_
    # International_Airport" already names directly, so in one batch
    # request both titles collapse to a single returned page. A page-keyed
    # alias map can only hand that one page back to ONE of the two inputs
    # and silently drops the other as "not an airport" -- this is the exact
    # bug that once left ICN->NRT missing from a fully-built route network.
    #
    # config.CACHE is redirected to an empty tmp_path for the same reason
    # as above: a warm real cache would make this pass regardless.
    monkeypatch.setattr(config, "CACHE", tmp_path)
    got = wikidata.iata_for_titles(["Narita_Airport", "Narita_International_Airport"])
    assert got["Narita_Airport"] == "NRT"
    assert got["Narita_International_Airport"] == "NRT"


# --- Refusal to persist a partially-crawled network (C1) ---------------------
#
# The network parquet is returned verbatim by every later call, so the old
# "will retry next run" messages named a retry that structurally could never
# happen. These tests pin that a partial crawl now aborts instead of becoming
# the permanent route network.


def _stub_route_network_inputs(monkeypatch, tmp_path, destinations, unresolved):
    """Point route_network at a tmp BUILD dir and fake every crawl collaborator."""
    monkeypatch.setattr(config, "BUILD", tmp_path)
    monkeypatch.setattr(
        routes.airports, "scheduled_airports",
        lambda: pl.DataFrame({"iata": ["ICN", "NRT"]}),
    )
    monkeypatch.setattr(routes, "_wikipedia_titles", lambda apts: {"ICN": "A", "NRT": "B"})
    monkeypatch.setattr(
        routes, "_crawl_destinations", lambda titles: (destinations, unresolved)
    )
    monkeypatch.setattr(routes.wikidata, "iata_for_titles", lambda titles: {})


def test_route_network_refuses_to_persist_a_partial_crawl(tmp_path, monkeypatch):
    _stub_route_network_inputs(
        monkeypatch, tmp_path, destinations={"ICN": ["B"]}, unresolved=["NRT"]
    )

    with pytest.raises(RuntimeError, match="refusing to persist a partial route network"):
        routes.route_network()

    assert not list(tmp_path.glob("routes*.parquet"))


def test_route_network_names_the_unresolved_count_and_a_sample(tmp_path, monkeypatch):
    _stub_route_network_inputs(
        monkeypatch, tmp_path,
        destinations={}, unresolved=[f"X{i:02d}" for i in range(30)],
    )

    with pytest.raises(RuntimeError) as excinfo:
        routes.route_network()
    assert "30 entries unresolved" in str(excinfo.value)
    assert "X00" in str(excinfo.value)


def _stub_full_network(monkeypatch, tmp_path, titles=None):
    """A crawl big enough to pass both gates; returns the list of crawl calls.

    Every airport flies to every other: 202 * 201 = 40,602 directed pairs,
    comfortably over the 20,000-pair implausibility floor, and ICN<->NRT is
    present so the sanity-pair gate passes too.
    """
    apts = pl.DataFrame({"iata": sorted({f"A{i:03d}" for i in range(200)} | {"ICN", "NRT"})})
    codes = apts["iata"].to_list()
    links = {"ICN": "Incheon_International_Airport"} if titles is None else titles
    monkeypatch.setattr(config, "BUILD", tmp_path)
    monkeypatch.setattr(routes.airports, "scheduled_airports", lambda: apts)
    monkeypatch.setattr(routes, "_wikipedia_titles", lambda a: dict(links))
    crawls: list[dict[str, str]] = []

    def crawl(titles_by_iata):
        crawls.append(titles_by_iata)
        return {c: [d for d in codes if d != c] for c in codes}, []

    monkeypatch.setattr(routes, "_crawl_destinations", crawl)
    monkeypatch.setattr(routes.wikidata, "iata_for_titles", lambda titles: {c: c for c in codes})
    return codes, links, crawls


def test_route_network_still_builds_when_nothing_is_unresolved(tmp_path, monkeypatch):
    """Companion to the refusal tests: the guard must not block a clean crawl.

    Without this, deleting the whole crawl and always raising would pass the
    two tests above.
    """
    codes, links, _ = _stub_full_network(monkeypatch, tmp_path)

    df = routes.route_network()

    assert routes._network_cache_path(codes, links).exists()
    assert len(df) == len(codes) * (len(codes) - 1)


# --- the cache must be the stamped file, and only that (CR13-3) --------------


def test_a_legacy_routes_parquet_never_wins_and_the_crawl_writes_the_stamped_file(
    tmp_path, monkeypatch, capsys
):
    """The legacy branch used to return `routes.parquet` WITHOUT writing the
    stamped file, so it won on that run and every run after: no parser,
    resolver or airport-table change could reach the network.

    Mutation, measured: restoring `return pl.read_parquet(legacy)` turns this
    red (one-row network, no stamped file, no crawl).
    """
    codes, links, crawls = _stub_full_network(monkeypatch, tmp_path)
    pl.DataFrame({"src": ["AAA"], "dst": ["BBB"]}).write_parquet(tmp_path / "routes.parquet")

    df = routes.route_network()

    assert len(crawls) == 1
    assert len(df) == len(codes) * (len(codes) - 1)
    assert routes._network_cache_path(codes, links).exists()
    assert "ignoring legacy routes.parquet" in capsys.readouterr().out

    # And the stamped file is what the next call reads, with no crawl.
    routes.route_network()
    assert len(crawls) == 1


def test_a_network_built_by_another_parser_is_a_miss(tmp_path, monkeypatch):
    """CR13-13 end to end: a parser fix must reach the network, not be
    answered from the parquet the old parser produced.

    Mutation, measured: dropping `_parser_key()` from `_network_cache_path`'s
    stamp turns this red (one crawl, not two).
    """
    _, _, crawls = _stub_full_network(monkeypatch, tmp_path)
    routes.route_network()
    monkeypatch.setattr(routes, "_LINK_RE", re.compile(r"\[\[([^\]|]+?)\]\]"))
    routes.route_network()
    assert len(crawls) == 2


def test_a_changed_article_link_is_a_miss(tmp_path, monkeypatch):
    """The crawl's input, not just its constants: OurAirports re-pointing an
    airport at another article must not be answered from the old network."""
    links = {"ICN": "Incheon_International_Airport"}
    _, _, crawls = _stub_full_network(monkeypatch, tmp_path, titles=links)
    routes.route_network()
    links["ICN"] = "Incheon_Airport"
    routes.route_network()
    assert len(crawls) == 2


# --- Confirmed-absent vs merely-unreturned articles --------------------------


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, body):
        self._body = body

    def get(self, *_args, **_kwargs):
        return _FakeResponse(self._body)


def _wikitext_body(pages):
    return {"batchcomplete": True, "query": {"pages": pages}}


def _content_page(title, text):
    return {"title": title, "revisions": [{"slots": {"main": {"content": text}}}]}


def test_missing_article_is_confirmed_absent_not_merely_unreturned():
    """A page the API marks "missing" is a permanent answer; a page it simply
    never mentions is not. Conflating them is how a failed fetch gets cached
    forever as an airport with no destinations.
    """
    body = _wikitext_body([
        _content_page("Alpha", "== Airlines and destinations ==\n[[Beta Airport]]\n"),
        {"title": "Gamma", "missing": True},
        # "Delta" is not mentioned at all.
    ])
    content, absent = routes._fetch_wikitext(_FakeClient(body), ["Alpha", "Gamma", "Delta"])

    assert set(content) == {"Alpha"}
    assert absent == {"Gamma"}
    assert "Delta" not in absent  # unresolved, not "this article does not exist"


def test_crawl_caches_none_only_for_confirmed_absent_and_reports_the_rest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    monkeypatch.setattr(
        routes, "_fetch_wikitext_with_retry",
        lambda client, titles: (
            {"Alpha": "== Airlines and destinations ==\n[[Beta Airport]]\n"},
            {"Gamma"},
        ),
    )

    cache, unresolved = routes._crawl_destinations(
        {"AAA": "Alpha", "GGG": "Gamma", "DDD": "Delta"}
    )

    assert cache["AAA"] == ["Beta_Airport"]
    assert cache["GGG"] is None      # enwiki confirms no such article
    assert "DDD" not in cache        # unconfirmed -> refetched next run
    assert unresolved == ["DDD"]


def test_crawl_reports_a_failed_batch_without_caching_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)

    def _boom(client, titles):
        raise RuntimeError("API error: readonly")

    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", _boom)

    cache, unresolved = routes._crawl_destinations({"AAA": "Alpha", "BBB": "Beta"})

    assert cache == {}
    assert sorted(unresolved) == ["AAA", "BBB"]


def test_a_batch_that_comes_back_paged_is_halved_until_it_resolves(tmp_path, monkeypatch):
    """A11 / CR-18: a batch of whole articles too big for one response comes
    back with a `continue`, and since the batch is whatever is still
    uncached, every re-run asked for the same titles and failed the same
    way -- route_network refused forever. Here any request for more than two
    titles pages; seven titles in one batch must all resolve, and an article
    that pages even alone stays unresolved without looping.

    Mutation performed and reverted: the split removed (a paged batch
    treated as failed) -> red, all seven unresolved.
    """
    from transport_maps.sources._utils import IncompleteResponse

    monkeypatch.setattr(config, "CACHE", tmp_path)
    monkeypatch.setattr(routes, "TITLES_PER_REQUEST", 8)
    asked: list[int] = []

    def fetch(client, titles):
        asked.append(len(titles))
        if len(titles) > 2 or "Huge" in titles:
            raise IncompleteResponse("API response incomplete (continue key present)")
        return {t: "== Airlines and destinations ==\n[[Hub Airport]]\n" for t in titles}, set()

    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", fetch)
    titles = {f"A{i}": f"Article{i}" for i in range(7)} | {"HHH": "Huge"}
    got, unresolved = routes._crawl_destinations(titles)

    assert unresolved == ["HHH"]
    assert got == {f"A{i}": ["Hub_Airport"] for i in range(7)}
    assert asked[0] == 8 and max(asked[1:]) < 8, asked
    assert routes._load_destination_cache().keys() == {f"Article{i}" for i in range(7)}


def test_the_crawl_cache_is_keyed_on_the_article_not_the_airport(tmp_path, monkeypatch):
    """OurAirports re-pointing a code at another article must refetch it, and
    an article already parsed for one code must not be fetched again for
    another. An IATA-keyed cache got the first wrong: the code was "cached",
    so the new article was never read.

    Mutation, measured: building `todo` from the codes not in the cache (the
    old keying) turns this red -- New_Article is never fetched.
    """
    monkeypatch.setattr(config, "CACHE", tmp_path)
    routes._save_destination_cache({"AAA": ["Old_Destination"], "Shared": ["Hub"]})
    fetched: list[list[str]] = []

    def fetch(client, titles):
        fetched.append(list(titles))
        return {t: "== Airlines and destinations ==\n[[Fresh Airport]]\n" for t in titles}, set()

    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", fetch)

    got, unresolved = routes._crawl_destinations(
        {"AAA": "New_Article", "BBB": "Shared", "CCC": "Shared"}
    )

    assert fetched == [["New_Article"]]
    assert got == {"AAA": ["Fresh_Airport"], "BBB": ["Hub"], "CCC": ["Hub"]}
    assert unresolved == []
