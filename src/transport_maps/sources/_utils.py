"""Shared utilities for sources modules."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from transport_maps._io import atomic_write, params_hash

# A server can ask for an arbitrarily long Retry-After; a crawl that sleeps a
# day on one header is indistinguishable from a hang.
MAX_RETRY_AFTER_S = 300.0


def _retry_after_seconds(value: str | None, attempt: int) -> float:
    """Parse a `Retry-After` header, falling back to exponential backoff.

    The header may be given as an integer number of seconds OR an HTTP-date
    (RFC 7231); a caller that only tries `float(value)` raises `ValueError`
    on the date form, which -- if that exception isn't specifically caught
    wherever the retry loop lives -- aborts the whole run instead of just
    backing off one batch.
    """
    if value is not None:
        try:
            return min(max(float(value), 0.0), MAX_RETRY_AFTER_S)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return min(max((dt - datetime.now(UTC)).total_seconds(), 0.0), MAX_RETRY_AFTER_S)
        except (TypeError, ValueError):
            pass
    return min(float(2**attempt), MAX_RETRY_AFTER_S)


def _validated_json(response, *, expect_key: str, require_batchcomplete: bool) -> dict:
    """Parse an httpx JSON response and validate its shape before trusting it.

    MediaWiki returns API-level errors (readonly, maxlag, an internal
    error, ...) as an `{"error": ...}` body with HTTP 200, so
    `raise_for_status()` never sees them. Treating that body's absent
    `query`/`entities` key as "these titles/qids resolved to nothing" is
    exactly how a whole batch got permanently cached as empty before.
    A `continue` key, or a query response missing `batchcomplete`, means
    the result is a partial page of a paginated response, not the whole
    answer -- also not safe to treat as final.
    """
    body = response.json()
    if "error" in body:
        raise RuntimeError(f"API error: {body['error']}")
    if "continue" in body:
        raise RuntimeError("API response incomplete (continue key present)")
    if require_batchcomplete and "batchcomplete" not in body:
        raise RuntimeError("API response missing 'batchcomplete'")
    if expect_key not in body:
        raise RuntimeError(f"API response missing {expect_key!r}")
    return body[expect_key]


# The atomic writer and the cache-key hash live in transport_maps._io. The
# emit and contour layers now import them from there directly -- this comment
# claimed they already did while four call sites (contour/grid.py,
# emit/{places,borders,airports_json}.py) still went through the shim below.
# These aliases remain only for the modules in THIS package, which import them
# under the underscored names throughout.
_atomic_write = atomic_write
def _refuse_partial(what: str, unresolved: list[str], remedy: str) -> None:
    """Abort rather than let a partially-crawled result become the cached one.

    The route network's parquet is returned verbatim by every later call with
    the same inputs, so a network written while part of the crawl was still
    unresolved is not a temporary
    state that a "retry next run" ever revisits -- it is permanent, and the
    only gates downstream (a 20,000-pair floor against ~68,000 real pairs, and
    the ICN-NRT sanity pair) would let roughly 70% of the crawl go missing
    unnoticed. Refuse to write instead. Per-item caches are still flushed
    first, so a re-run resumes from exactly what is left.
    """
    if not unresolved:
        return
    sample = ", ".join(sorted(unresolved)[:10])
    raise RuntimeError(
        f"{what} left {len(unresolved)} entries unresolved (e.g. {sample}); "
        f"refusing to persist a partial route network -- {remedy}"
    )


_params_hash = params_hash
