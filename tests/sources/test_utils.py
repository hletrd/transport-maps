"""The two crawl guards in sources/_utils.py, which had no tests at all.

Both are pure and need no network. `_validated_json` is the guard against
MediaWiki's HTTP-200 error bodies -- the bug its own docstring records having
already shipped once, permanently caching a whole batch as empty -- and
deleting it left the entire suite green.
"""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from transport_maps.sources import _utils


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


# ---- _validated_json ----

def test_a_200_with_an_error_body_is_refused_not_read_as_empty():
    """MediaWiki reports readonly, maxlag and internal errors as {"error": ...}
    with HTTP 200, so raise_for_status never sees them. Reading the absent
    `query` key as "these titles resolved to nothing" is how a batch got
    permanently cached as empty."""
    r = _Resp({"error": {"code": "readonly", "info": "database locked"}})
    with pytest.raises(RuntimeError, match="API error"):
        _utils._validated_json(r, expect_key="query", require_batchcomplete=True)


def test_a_paginated_response_is_refused():
    r = _Resp({"batchcomplete": "", "query": {"pages": {}}, "continue": {"gcmcontinue": "x"}})
    with pytest.raises(RuntimeError, match="continue"):
        _utils._validated_json(r, expect_key="query", require_batchcomplete=True)


def test_a_query_without_batchcomplete_is_refused():
    r = _Resp({"query": {"pages": {}}})
    with pytest.raises(RuntimeError, match="batchcomplete"):
        _utils._validated_json(r, expect_key="query", require_batchcomplete=True)


def test_batchcomplete_is_not_required_for_entity_responses():
    """wbgetentities does not send batchcomplete; requiring it there would
    refuse every valid Wikidata reply."""
    r = _Resp({"entities": {"Q42": {}}})
    assert _utils._validated_json(r, expect_key="entities", require_batchcomplete=False) == {"Q42": {}}


def test_a_missing_expected_key_is_refused():
    r = _Resp({"batchcomplete": ""})
    with pytest.raises(RuntimeError, match="query"):
        _utils._validated_json(r, expect_key="query", require_batchcomplete=True)


def test_a_well_formed_response_returns_the_payload():
    r = _Resp({"batchcomplete": "", "query": {"pages": {"1": {"title": "Incheon"}}}})
    assert _utils._validated_json(r, expect_key="query", require_batchcomplete=True) == {
        "pages": {"1": {"title": "Incheon"}}}


# ---- _retry_after_seconds ----

def test_an_integer_retry_after_is_used_as_given():
    assert _utils._retry_after_seconds("7", attempt=0) == 7.0


def test_an_http_date_retry_after_is_parsed_not_treated_as_an_error():
    """RFC 7231 allows the date form. A caller that only tries float() raises
    ValueError on it, which aborts the run instead of backing off one batch."""
    when = datetime.now(UTC) + timedelta(seconds=30)
    got = _utils._retry_after_seconds(format_datetime(when), attempt=0)
    assert 20 <= got <= 40, got


def test_a_date_in_the_past_never_goes_negative():
    when = datetime.now(UTC) - timedelta(hours=1)
    assert _utils._retry_after_seconds(format_datetime(when), attempt=0) == 0.0


def test_an_unparseable_header_falls_back_to_exponential_backoff():
    assert _utils._retry_after_seconds("soon-ish", attempt=3) == 8.0
    assert _utils._retry_after_seconds(None, attempt=4) == 16.0


def test_every_path_is_capped():
    """An hour-long Retry-After would hang a build; the cap is the point."""
    cap = _utils.MAX_RETRY_AFTER_S
    assert _utils._retry_after_seconds("100000", attempt=0) == cap
    assert _utils._retry_after_seconds(None, attempt=40) == cap
    far = datetime.now(UTC) + timedelta(days=1)
    assert _utils._retry_after_seconds(format_datetime(far), attempt=0) == cap
