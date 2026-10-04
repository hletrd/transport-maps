import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import routes, wikidata

FIXTURE = Path(__file__).parent.parent / "fixtures" / "icn_wikitext.txt"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "routes"
L = routes.Listing


def _titles(listings: list[routes.Listing]) -> list[str]:
    return [x.title for x in listings]


def _section(*titles: str) -> str:
    """A destinations section listing `titles` in one row of the list
    template, under no airline: each parses to `Listing(title)`."""
    links = ", ".join(f"[[{t}]]" for t in titles)
    return f"== Airlines and destinations ==\n{{{{Airport destination list\n| | {links}\n}}}}\n"


def test_parses_destination_article_titles_from_real_page():
    titles = _titles(routes.parse_destinations(FIXTURE.read_text(encoding="utf-8")))
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
        "{{Airport destination list\n"
        "|[[Test Airlines]]|[[File:Some_icon.svg]] [[Category:Test airports]] "
        "[[Test Destination Airport]]\n"
        "}}\n"
    )
    titles = _titles(routes.parse_destinations(wikitext))
    assert "Test_Destination_Airport" in titles
    assert not any(t.startswith(("File:", "Category:", "Help:")) for t in titles)


def test_ignores_cargo_subsection():
    titles = _titles(routes.parse_destinations(FIXTURE.read_text(encoding="utf-8")))
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
        "{{Airport destination list\n| [[Alpha Airline]] | [[Alpha Airport]]\n}}\n"
        "===Cargo===\n"
        "{{Airport destination list\n| [[Cargo Only Co]] | [[Cargo Destination Airport]]\n}}\n"
        "===More Passenger===\n"
        "{{Airport destination list\n| [[Beta Airline]] | [[Beta Airport]]\n}}\n"
        "== Ground transportation ==\n"
        "Some unrelated text.\n"
    )
    titles = _titles(routes.parse_destinations(wikitext))
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
    titles = _titles(routes.parse_destinations((FIXTURES / "level3_section.wikitext").read_text()))
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
        "{{Airport destination list\n| | [[Alpha Airport]]\n}}\n"
        "=== International ===\n"
        "{{Airport destination list\n| | [[Beta Airport]]\n}}\n"
        "== Statistics ==\n"
        "{{Airport destination list\n| | [[Gamma Airport]]\n}}\n"
    )
    assert _titles(routes.parse_destinations(wikitext)) == ["Alpha_Airport", "Beta_Airport"]


def test_a_link_with_a_section_fragment_keeps_its_destination():
    """CR13-6. `[[Article#Section|label]]` used to match nothing: the title
    capture stops at "#", and the regex then demanded "|" or "]]". Three of
    the four destination airports below were silently dropped. The fragment is not
    part of the title Wikidata resolves, so it is cut, not kept.

    Mutation, measured: restoring the old `_LINK_RE` turns this red.
    """
    titles = _titles(routes.parse_destinations((FIXTURES / "fragment_links.wikitext").read_text()))
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


@pytest.fixture(autouse=True)
def _online():
    """The crawl's network layer is stubbed in every test here; what is under
    test is what it does when it may ask (G2: the suite runs offline)."""
    from transport_maps.sources import _fetch

    _fetch.set_offline(False)


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
        monkeypatch, tmp_path, destinations={"ICN": [L("B")]}, unresolved=["NRT"]
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


def _stub_full_network(monkeypatch, tmp_path, titles=None, builds=None):
    """A crawl big enough to pass both gates; returns the list of crawl calls.

    Every airport flies to every other: 202 * 201 = 40,602 directed pairs,
    comfortably over the 20,000-pair implausibility floor, and ICN<->NRT is
    present so the sanity-pair gate passes too.

    The crawl runs on EVERY call since G2 -- it is the freshness check, and
    costs nothing when the article cache is fresh -- so the number of crawls
    no longer says whether the network was rebuilt. `builds`, if given,
    collects the name of every network parquet actually written.
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
        return {c: [L(d) for d in codes if d != c] for c in codes}, []

    monkeypatch.setattr(routes, "_crawl_destinations", crawl)
    monkeypatch.setattr(routes.wikidata, "iata_for_titles", lambda titles: {c: c for c in codes})
    if builds is not None:
        real = routes._atomic_write
        monkeypatch.setattr(routes, "_atomic_write",
                            lambda path, fn: (builds.append(path.name), real(path, fn)))
    return codes, links, crawls


def test_route_network_still_builds_when_nothing_is_unresolved(tmp_path, monkeypatch):
    """Companion to the refusal tests: the guard must not block a clean crawl.

    Without this, deleting the whole crawl and always raising would pass the
    two tests above.
    """
    codes, links, _ = _stub_full_network(monkeypatch, tmp_path)

    df = routes.route_network()

    assert len(list(tmp_path.glob("routes_*.parquet"))) == 1
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
    builds: list[str] = []
    codes, links, crawls = _stub_full_network(monkeypatch, tmp_path, builds=builds)
    pl.DataFrame({"src": ["AAA"], "dst": ["BBB"]}).write_parquet(tmp_path / "routes.parquet")

    df = routes.route_network()

    assert len(builds) == 1
    assert len(df) == len(codes) * (len(codes) - 1)
    assert (tmp_path / builds[0]).exists() and builds[0] != "routes.parquet"
    assert "ignoring legacy routes.parquet" in capsys.readouterr().out

    # And the stamped file is what the next call reads, with no rebuild.
    routes.route_network()
    assert len(builds) == 1


def test_a_network_built_by_another_parser_is_a_miss(tmp_path, monkeypatch):
    """CR13-13 end to end: a parser fix must reach the network, not be
    answered from the parquet the old parser produced.

    Mutation, measured: dropping `_parser_key()` from `_network_cache_path`'s
    stamp turns this red (one build, not two).
    """
    builds: list[str] = []
    _stub_full_network(monkeypatch, tmp_path, builds=builds)
    routes.route_network()
    monkeypatch.setattr(routes, "_LINK_RE", re.compile(r"\[\[([^\]|]+?)\]\]"))
    routes.route_network()
    assert len(builds) == 2


def test_a_changed_article_link_is_a_miss(tmp_path, monkeypatch):
    """The crawl's input, not just its constants: OurAirports re-pointing an
    airport at another article must not be answered from the old network."""
    links = {"ICN": "Incheon_International_Airport"}
    builds: list[str] = []
    _stub_full_network(monkeypatch, tmp_path, titles=links, builds=builds)
    routes.route_network()
    links["ICN"] = "Incheon_Airport"
    routes.route_network()
    assert len(builds) == 2


def test_a_changed_crawl_is_a_miss_and_an_unchanged_one_is_not(tmp_path, monkeypatch):
    """G2: the same airports and links, refetched, can say something else.

    Mutation: drop `crawl` from `_network_cache_path`'s stamp -> red (the
    third call reads back the network the old articles made)."""
    builds: list[str] = []
    codes, _, _ = _stub_full_network(monkeypatch, tmp_path, builds=builds)
    routes.route_network()
    routes.route_network()
    assert len(builds) == 1, "an unchanged crawl rebuilt the network"
    # A000 stops being served: its article lists nothing and no article lists it.
    monkeypatch.setattr(routes, "_crawl_destinations", lambda titles: (
        {c: [] if c == "A000" else [L(d) for d in codes if d not in (c, "A000")]
         for c in codes}, []))
    df = routes.route_network()
    assert len(builds) == 2
    assert df.filter((pl.col("src") == "A000") | (pl.col("dst") == "A000")).is_empty()


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
        _content_page("Alpha", _section("Beta Airport")),
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
            {"Alpha": _section("Beta Airport")},
            {"Gamma"},
        ),
    )

    cache, unresolved = routes._crawl_destinations(
        {"AAA": "Alpha", "GGG": "Gamma", "DDD": "Delta"}
    )

    assert cache["AAA"] == [L("Beta_Airport")]
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
        return {t: _section("Hub Airport") for t in titles}, set()

    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", fetch)
    titles = {f"A{i}": f"Article{i}" for i in range(7)} | {"HHH": "Huge"}
    got, unresolved = routes._crawl_destinations(titles)

    assert unresolved == ["HHH"]
    assert got == {f"A{i}": [L("Hub_Airport")] for i in range(7)}
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
    now = _now()
    routes._save_destination_cache({"AAA": [L("Old_Destination")], "Shared": [L("Hub")]},
                                   {"AAA": now, "Shared": now})
    fetched: list[list[str]] = []

    def fetch(client, titles):
        fetched.append(list(titles))
        return {t: _section("Fresh Airport") for t in titles}, set()

    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", fetch)

    got, unresolved = routes._crawl_destinations(
        {"AAA": "New_Article", "BBB": "Shared", "CCC": "Shared"}
    )

    assert fetched == [["New_Article"]]
    assert got == {"AAA": [L("Fresh_Airport")], "BBB": [L("Hub")], "CCC": [L("Hub")]}
    assert unresolved == []


# --- G2: the crawl is refreshed every build, within ARTICLE_MAX_AGE ---------


def _now(**ago) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(**ago)).replace(microsecond=0).isoformat()


def _fresh_wikitext(titles):
    return {t: _section("Fresh Airport") for t in titles}, set()


def test_an_article_older_than_the_max_age_is_refetched_and_a_fresh_one_is_not(
        tmp_path, monkeypatch):
    """Mutation: build `todo` from the uncached titles only (the pre-G2
    crawl) -> red, nothing is refetched and Old keeps its old parse."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    routes._save_destination_cache({"Old": [L("Stale_Airport")], "New": [L("Hub")]},
                                   {"Old": _now(hours=25), "New": _now(hours=1)})
    fetched: list[list[str]] = []
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry",
                        lambda client, titles: fetched.append(list(titles)) or _fresh_wikitext(titles))

    got, unresolved = routes._crawl_destinations({"AAA": "Old", "BBB": "New"})

    assert fetched == [["Old"]]
    assert got == {"AAA": [L("Fresh_Airport")], "BBB": [L("Hub")]} and unresolved == []
    assert routes._load_fetched_at()["Old"] > _now(minutes=5)


def test_a_cache_written_before_g2_is_refetched_whole(tmp_path, monkeypatch):
    """No `fetched_at` at all means no article's age is known."""
    import json

    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "airline_destinations.json").write_text(json.dumps(
        {"_parser_key": routes._parser_key(), "articles": {"A": [["X"]], "B": [["Y"]]}}))
    fetched: list[str] = []
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry",
                        lambda client, titles: fetched.extend(titles) or _fresh_wikitext(titles))
    routes._crawl_destinations({"AAA": "A", "BBB": "B"})
    assert sorted(fetched) == ["A", "B"]


def test_a_failed_refetch_keeps_the_cached_parse_and_warns(tmp_path, monkeypatch, capsys):
    """Wikipedia being down must not fail a build that holds a parse of every
    article. Mutation: count a failed refetch as unresolved -> red."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    old = _now(days=3)
    routes._save_destination_cache({"Old": [L("Stale_Airport")]}, {"Old": old})

    def boom(client, titles):
        raise RuntimeError("API error: readonly")
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", boom)

    got, unresolved = routes._crawl_destinations({"AAA": "Old"})

    assert got == {"AAA": [L("Stale_Airport")]} and unresolved == []
    assert "could not be refetched" in capsys.readouterr().out
    assert routes._load_fetched_at()["Old"] == old, "a failed refetch must stay stale"


def test_offline_fetches_nothing_and_reads_the_cache(tmp_path, monkeypatch):
    """Mutation: ignore `_fetch.offline()` in the crawl -> red."""
    from transport_maps.sources import _fetch

    monkeypatch.setattr(config, "CACHE", tmp_path)
    routes._save_destination_cache({"Old": [L("Stale_Airport")]}, {"Old": _now(days=3)})
    _fetch.set_offline(True)

    def boom(client, titles):
        raise AssertionError("fetched while offline")
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry", boom)

    got, unresolved = routes._crawl_destinations({"AAA": "Old", "BBB": "Never_Fetched"})
    assert got == {"AAA": [L("Stale_Airport")]}
    assert unresolved == ["BBB"], "offline, an article never fetched is unresolved"


def test_the_crawl_is_recorded_for_the_build_identity(tmp_path, monkeypatch):
    from transport_maps.sources import _fetch

    monkeypatch.setattr(config, "CACHE", tmp_path)
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry",
                        lambda client, titles: _fresh_wikitext(titles))
    routes._crawl_destinations({"AAA": "A", "BBB": "B"})
    rec = _fetch.used()["wikipedia:airline-destinations"]
    assert rec["articles"] == 2 and rec["fetchedFrom"] and rec["fetchedTo"]


# --- year-round scheduled service only (owner decision, 2026-10-04) --------
#
# The fixtures are real sections (October 2026 revisions), trimmed. The day
# every date below is judged against is the decision's own.

DAY = date(2026, 10, 4)


def _parse(name: str) -> list[routes.Listing]:
    return routes.parse_destinations((FIXTURES / name).read_text(encoding="utf-8"))


def _by_title(listings: list[routes.Listing]) -> dict[str, list[routes.Listing]]:
    out: dict[str, list[routes.Listing]] = {}
    for x in listings:
        out.setdefault(x.title, []).append(x)
    return out


def test_adelaide_labels_mark_seasonal_and_charter_to_the_end_of_the_cell():
    """The reported case: China Eastern's Adelaide-Pudong row is all seasonal
    ("''' Seasonal:'''", a stray space inside the bold), and a label runs to
    the end of its cell, past the <br/>s, so Virgin's Launceston is seasonal
    and Olympic Dam after the next label is charter.

    Mutation, measured: `_label_service` always returning None -> red."""
    got = _by_title(_parse("adelaide_airport.wikitext"))
    assert got["Shanghai_Pudong_International_Airport"] == [
        L("Shanghai_Pudong_International_Airport", "seasonal", airline="China_Eastern_Airlines")]
    assert [x.service for x in got["Christchurch_Airport"]] == ["seasonal"]
    assert [x.service for x in got["Hong_Kong_International_Airport"]] == ["seasonal"]
    assert [x.service for x in got["Launceston_Airport"]] == ["seasonal"]
    assert {x.service for x in got["Ballera_Airport"] + got["Carrapateena_Airport"]} == {"charter"}
    # Olympic Dam twice: Alliance's scheduled flights, and Virgin's charters.
    assert {(x.airline, x.service) for x in got["Olympic_Dam_Airport"]} == {
        ("Alliance_Airlines", "scheduled"), ("Virgin_Australia", "charter")}
    # Auckland three times: Air NZ year-round, Qantas seasonal ("'''Seasonal: '''"),
    # Qatar to end on 8 December.
    assert {(x.airline, x.service, x.change, x.on) for x in got["Auckland_Airport"]} == {
        ("Air_New_Zealand", "scheduled", None, None),
        ("Qantas", "seasonal", None, None),
        ("Qatar_Airways", "scheduled", "ends", "2026-12-08")}
    assert [x.service for x in got["Singapore_Changi_Airport"]] == ["scheduled"]


def test_references_prose_and_cargo_are_not_destinations():
    """A citation's `publisher=[[Roxby Council]]`, an aircraft in the prose
    under the table, and the Cargo subsection. Mutation, measured: dropping
    the two reference alternatives from _NOISE_RE -> red (Roxby_Council)."""
    titles = _titles(_parse("adelaide_airport.wikitext"))
    for not_a_destination in ("Roxby_Council", "Boeing_787-9_Dreamliner",
                              "Western_Sydney_Airport", "Qantas_Freight"):
        assert not_a_destination not in titles


def test_pudong_dated_changes_bind_to_the_link_before_them():
    """Mutation, measured: binding a change to the cell's first link instead
    of its last (`cell[:covers]`) -> red."""
    got = {x.title: x for x in _parse("shanghai_pudong_airport.wikitext")}
    assert got["Houari_Boumediene_Airport"][2:4] == ("begins", "2026-10-26")
    assert got["Bangkok–Suvarnabhumi"][2:4] == ("resumes", "2026-10-25")
    assert got["Josep_Tarradellas_Barcelona–El_Prat_Airport"][2:4] == (None, None)
    assert got["Mactan–Cebu_International_Airport"][2:4] == ("resumes", "2026-11-18")
    assert got["Ninoy_Aquino_International_Airport"][2:4] == (None, None)
    assert got["Dunhuang_Mogao_International_Airport"][2:4] == ("ends", "2026-10-11")
    assert got["Chinggis_Khaan_International_Airport"][2:4] == ("resumes", "2026-10-29")
    assert got["Adelaide_Airport"] == L("Adelaide_Airport", "seasonal",
                                        airline="China_Eastern_Airlines")


def test_us_dates_and_a_colon_outside_the_bold():
    got = _by_title(_parse("denver_airport.wikitext"))
    # '''Seasonal''': -- the colon outside the bold -- and a US-style end date.
    assert got["Charles_de_Gaulle_Airport"] == [
        L("Charles_de_Gaulle_Airport", "seasonal", "ends", "2026-10-10", "Air_France")]
    assert [x.service for x in got["Ted_Stevens_Anchorage_International_Airport"]] == ["seasonal"]
    assert [x.service for x in got["Seattle–Tacoma_International_Airport"]] == ["scheduled"]
    assert got["McKinney_National_Airport"][0][2:4] == ("begins", "2026-12-16")
    assert got["Fort_Lauderdale-Hollywood_International_Airport"][0][2:4] == (
        "begins", "2026-11-20")
    assert [x.service for x in got["Ronald_Reagan_Washington_National_Airport"]] == ["scheduled"]
    assert [x.service for x in got["Rhode_Island_T._F._Green_International_Airport"]] == [
        "seasonal"]
    # The next row starts scheduled again.
    assert [x.service for x in got["Hartsfield–Jackson_Atlanta_International_Airport"]] == [
        "scheduled"]
    # The top-destinations table is not the destination list.
    assert "Phoenix_Sky_Harbor_International_Airport" not in got


def test_a_destination_map_is_not_read():
    """Edmonton's map marks seasonal (green) and future (blue) destinations
    by pin colour alone, so Prince George -- a future destination only on the
    map -- must not appear, and Kamloops only once, as the table's seasonal.

    Mutation, measured: `map` taken out of _NOT_DESTINATIONS_TEMPLATE_RE ->
    red."""
    got = _by_title(_parse("edmonton_airport.wikitext"))
    assert "Prince_George_Airport" not in got
    assert got["Kamloops_Airport"] == [L("Kamloops_Airport", "seasonal", airline="WestJet_Encore")]
    assert [x.service for x in got["Calgary_International_Airport"]] == ["scheduled"]
    # The hub sentence above the table is prose.
    assert "Flair_Airlines" not in got


def test_assorted_forms():
    """Mutation, measured: reading links outside a table (dropping the
    `"list" in stack or tables` condition) -> red on San Francisco and
    Churchill Falls; `(suspended until ...)` read as plain "suspended" ->
    red on Dubai; a `<br>` ending a label's scope (`<br\\s*/?>` added to
    _CELL_END_RE) -> red on Rome."""
    got = _by_title(_parse("assorted_rows.wikitext"))

    def only(title):
        (x,) = got[title]
        return x.service, x.change, x.on

    # "(both begin ...)" covers the two links before it.
    assert only("Beijing_Capital_International_Airport") == ("scheduled", "begins", "2026-10-26")
    assert only("Copenhagen_Airport") == ("scheduled", "begins", "2026-10-26")
    # "(suspended until <date>)" is a resumption; "(suspended)" has no date.
    assert {x[1:4] for x in got["Dubai_International_Airport"]} == {
        ("scheduled", "resumes", "2027-01-18"), ("scheduled", "suspended", None)}
    assert only("Dublin_Airport") == ("scheduled", None, None)
    # An unbolded "Charter:", and any other label ("Hajj & Umrah:").
    assert only("Contamana_Airport") == ("charter", None, None)
    assert only("King_Abdulaziz_International_Airport") == ("other", None, None)
    assert only("Benina_International_Airport") == ("scheduled", None, None)
    # A class in parentheses after the link reclassifies that link only.
    assert only("New_Chitose_Airport") == ("seasonal", None, None)
    assert only("Haneda_Airport") == ("scheduled", None, None)
    assert only("Akron–Canton_Airport") == ("charter", None, None)
    # A label that ends its line still labels the next line; and a seasonal
    # list that wraps at a <br /> (the comma before it) stays seasonal.
    assert only("Charlotte_Douglas_International_Airport") == ("scheduled", None, None)
    assert only("O'Hare_International_Airport") == ("seasonal", None, None)
    assert only("Philadelphia_International_Airport") == ("seasonal", None, None)
    assert [only(t)[0] for t in ("Athens_International_Airport", "London–Gatwick",
                                 "Rome–Fiumicino")] == ["seasonal"] * 3
    # Three classes in one row.
    assert [only(t)[0] for t in ("Gatwick_Airport", "Glasgow_Airport", "Guernsey_Airport")] == [
        "scheduled", "seasonal", "seasonal charter"]
    # The prose above the table, the statistics table below it and the
    # historical and charter subsections all name airports; only the
    # table's seasonal row may list Denver and San Francisco.
    assert {x.service for x in got["San_Francisco_International_Airport"]} == {"seasonal"}
    assert {(x.airline, x.service) for x in got["Denver_International_Airport"]} == {
        ("Air_Canada", "scheduled"), ("United_Express", "seasonal")}
    for absent in ("Churchill_Falls,_Labrador", "Medical_evacuation", "SkyWest_Airlines"):
        assert absent not in got


def test_a_wikitable_row_names_its_airline():
    """Faisalabad's list is a wikitable whose cells are split by "||". Read
    as two cell ends around an empty cell, every destination's airline was
    "" -- and two airlines whose listings must not veto each other
    (_year_round_pairs) became one.

    Mutation, measured: `_CELL_END_RE = r"\\|"` -> red."""
    got = _by_title(_parse("faisalabad_airport.wikitext"))
    assert {x.airline for x in got["Jinnah_International_Airport"]} == {
        "Fly_Jinnah", "Pakistan_International_Airlines"}
    assert {x.airline for x in got["Dubai_International_Airport"]} == {
        "flydubai", "Pakistan_International_Airlines"}
    assert all(x.service == "scheduled" for xs in got.values() for x in xs)
    # The table header and the Cargo subsection are not destinations.
    assert "Islamabad_International_Airport" not in got


@pytest.mark.parametrize("change,text,on", [
    ("begins", " 1 June 2026", "2026-06-01"),
    ("begins", " October 25, 2026", "2026-10-25"),
    ("begins", " Sept. 3, 2026", "2026-09-03"),
    ("begins", " June 2027", "2027-06-30"),     # a month: its last day for a start
    ("ends", " June 2027", "2027-06-01"),       # ... and its first for an end
    ("resumes", " 2027", "2027-12-31"),
    ("ends", " 2027", "2027-01-01"),
    ("begins", " TBA", None),
    ("begins", " summer 2027", None),
    ("begins", " 31 February 2027", None),
])
def test_dates_are_read_at_the_conservative_end(change, text, on):
    """Mutation, measured: `late = False` (a month read as its first day
    for a start) -> the "June 2027" begins case is red."""
    assert routes._change_date(change, text) == on


@pytest.mark.parametrize("listing,kept", [
    (L("X"), True),
    (L("X", "seasonal"), False),
    (L("X", "charter"), False),
    (L("X", "seasonal charter"), False),
    (L("X", "other"), False),
    (L("X", change="suspended"), False),
    (L("X", change="begins"), False),                    # undated
    (L("X", change="begins", on="2026-10-04"), True),    # on the day: flying
    (L("X", change="begins", on="2026-10-05"), False),
    (L("X", change="resumes", on="2026-10-03"), True),
    (L("X", change="resumes", on="2026-10-25"), False),
    (L("X", change="ends", on="2026-10-05"), True),
    (L("X", change="ends", on="2026-10-04"), False),     # ends on the day: gone
    (L("X", "seasonal", "ends", "2027-01-01"), False),
])
def test_left_out(listing, kept):
    """Mutation, measured: `on < day` for a start (instead of `<=`) -> the
    on-the-day begins case is red; `on >= day` for an end -> its case."""
    assert (routes._left_out(listing, DAY) is None) is kept


def _pairs(destinations, resolved, valid, day=DAY):
    pairs, left_out, disputed = routes._year_round_pairs(destinations, resolved, valid, day)
    return {tuple(sorted(p)) for p in pairs}, left_out, disputed


_RESOLVE = {
    "Adelaide_Airport": "ADL", "Shanghai_Pudong_International_Airport": "PVG",
    "Sydney_Airport": "SYD", "Houari_Boumediene_Airport": "ALG",
    "Dunhuang_Mogao_International_Airport": "DNH", "Auckland_Airport": "AKL",
    "Singapore_Changi_Airport": "SIN", "Kota_Kinabalu_International_Airport": "BKI",
}


def test_pudong_adelaide_is_not_a_route_and_the_dates_follow_the_day():
    """The reported case end to end, from both real articles: each lists the
    other only as seasonal, so the pair is gone, while Pudong-Sydney (China
    Eastern, year-round) stays. Algiers begins 26 October and Dunhuang ends
    11 October, so the network depends on the day it is built.

    Mutation, measured: `_left_out` returning None for every listing (the
    rebuild-28 behaviour) -> red on ADL-PVG."""
    destinations = {"ADL": _parse("adelaide_airport.wikitext"),
                    "PVG": _parse("shanghai_pudong_airport.wikitext")}
    valid = set(_RESOLVE.values())
    pairs, left_out, _ = _pairs(destinations, _RESOLVE, valid)
    assert ("ADL", "PVG") not in pairs
    assert {("PVG", "SYD"), ("ADL", "SYD"), ("ADL", "SIN"), ("AKL", "PVG")} <= pairs
    assert ("ALG", "PVG") not in pairs and ("DNH", "PVG") in pairs
    assert left_out["seasonal"] >= 2
    # Kota Kinabalu: AirAsia year-round, Spring seasonal -> one airline suffices.
    assert ("BKI", "PVG") in pairs

    later, _, _ = _pairs(destinations, _RESOLVE, valid, date(2026, 10, 26))
    assert ("ALG", "PVG") in later and ("DNH", "PVG") not in later
    assert ("ADL", "PVG") not in later


def test_two_articles_that_disagree_about_one_airline_leave_the_pair_out():
    """Aberdeen lists easyJet's Paris flights as year-round, Charles de
    Gaulle lists the same flights as seasonal (both real, October 2026). The
    airline links differ in case ([[EasyJet]] / [[easyJet]]) and are one
    airline. A second airline that flies the pair year-round keeps it.

    Mutation, measured: keeping a pair when ANY listing is year-round (the
    union rule) -> red on the first assertion; dropping `.casefold()` -> red
    as well."""
    resolved = {"Aberdeen_Airport": "ABZ", "Charles_de_Gaulle_Airport": "CDG"}
    valid = {"ABZ", "CDG"}
    abz = [L("Charles_de_Gaulle_Airport", airline="EasyJet")]
    cdg = [L("Aberdeen_Airport", "seasonal", airline="easyJet")]
    pairs, _, disputed = _pairs({"ABZ": abz, "CDG": cdg}, resolved, valid)
    assert pairs == set() and disputed == 1

    cdg_too = cdg + [L("Aberdeen_Airport", airline="Air_France")]
    pairs, _, disputed = _pairs({"ABZ": abz, "CDG": cdg_too}, resolved, valid)
    assert pairs == {("ABZ", "CDG")} and disputed == 0

    # An article that does not list the pair at all does not veto it.
    pairs, _, _ = _pairs({"ABZ": abz, "CDG": []}, resolved, valid)
    assert pairs == {("ABZ", "CDG")}


def test_the_service_date_is_fixed_per_process_and_can_be_pinned(monkeypatch):
    """Mutation, measured: not keeping `_service_date` -> red (the second
    call reads the changed environment)."""
    from datetime import UTC, datetime

    monkeypatch.setattr(routes, "_service_date", None)
    monkeypatch.setenv(routes.SERVICE_DATE_ENV, "2026-10-04")
    assert routes.service_date() == DAY
    monkeypatch.setenv(routes.SERVICE_DATE_ENV, "2027-01-01")
    assert routes.service_date() == DAY
    monkeypatch.setattr(routes, "_service_date", None)
    monkeypatch.delenv(routes.SERVICE_DATE_ENV)
    assert routes.service_date() == datetime.now(UTC).date()


def test_a_route_that_begins_reaches_the_network_on_its_day(tmp_path, monkeypatch):
    """The network's key carries the service date: built again on the day a
    listed route begins, the same crawl must not be read back from the
    parquet the day before made.

    Mutation, measured: dropping `day.isoformat()` from
    `_network_cache_path`'s stamp -> red (one build; A000-A001 still
    missing on the second day)."""
    builds: list[str] = []
    codes, _, _ = _stub_full_network(monkeypatch, tmp_path, builds=builds)
    monkeypatch.setattr(routes, "_crawl_destinations", lambda titles: (
        {c: [L(d, change="begins", on="2026-10-05") if {c, d} == {"A000", "A001"} else L(d)
             for d in codes if d != c] for c in codes}, []))
    monkeypatch.setattr(routes, "_service_date", DAY)
    df = routes.route_network()
    assert df.filter((pl.col("src") == "A000") & (pl.col("dst") == "A001")).is_empty()
    monkeypatch.setattr(routes, "_service_date", date(2026, 10, 5))
    df = routes.route_network()
    assert len(builds) == 2
    assert not df.filter((pl.col("src") == "A000") & (pl.col("dst") == "A001")).is_empty()


def test_the_service_date_is_recorded_for_the_build_identity(tmp_path, monkeypatch):
    from transport_maps.sources import _fetch

    monkeypatch.setattr(config, "CACHE", tmp_path)
    monkeypatch.setattr(routes, "_service_date", DAY)
    monkeypatch.setattr(routes, "_fetch_wikitext_with_retry",
                        lambda client, titles: _fresh_wikitext(titles))
    routes._crawl_destinations({"AAA": "A"})
    assert _fetch.used()["wikipedia:airline-destinations"]["serviceDate"] == "2026-10-04"
