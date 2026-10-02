"""OurAirports -> airports with scheduled passenger service."""

import hashlib

import polars as pl

from transport_maps import config
from transport_maps.sources import _fetch
from transport_maps.sources._utils import _atomic_write, _params_hash

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

SIZE_BY_TYPE = {
    "large_airport": "large",
    "medium_airport": "medium",
    "small_airport": "small",
}

REQUIRED_SOURCE_COLUMNS = {
    "type", "name", "latitude_deg", "longitude_deg",
    "iso_country", "scheduled_service", "iata_code",
}


def _download() -> bytes:
    """The OurAirports CSV, checked against the upstream once per build (G2)."""
    config.ensure_dirs()
    return _fetch.fetch(AIRPORTS_URL, config.CACHE / "ourairports.csv", timeout=120) \
        .path.read_bytes()


def _table_cache_path(source: str):
    """Cache path stamped with the constants that determine the table's rows,
    and with `source`, the sha256 of the CSV they were applied to.

    Changing which OurAirports `type` values count as scheduled service, or
    which source columns are required, must produce a cache miss rather than
    silently reading back the table built under the old rules. So must a new
    OurAirports download: the URL alone named a file that changes daily.
    """
    stamp = _params_hash(AIRPORTS_URL, SIZE_BY_TYPE, sorted(REQUIRED_SOURCE_COLUMNS), source)
    return config.BUILD / f"airports_{stamp}.parquet"


def scheduled_airports() -> pl.DataFrame:
    # The key is the hash of the bytes about to be parsed, so the table can
    # never be one built from another download.
    data = _download()
    out = _table_cache_path(hashlib.sha256(data).hexdigest())
    if out.exists():
        return pl.read_parquet(out)

    raw = pl.read_csv(data, infer_schema_length=10_000)
    missing = REQUIRED_SOURCE_COLUMNS - set(raw.columns)
    if missing:
        raise RuntimeError(f"OurAirports schema changed; missing columns: {sorted(missing)}")

    df = (
        raw.filter(
            (pl.col("scheduled_service") == "yes")
            & pl.col("type").is_in(list(SIZE_BY_TYPE))
            & pl.col("iata_code").is_not_null()
            & (pl.col("iata_code").str.len_chars() == 3)
        )
        .select(
            pl.col("iata_code").alias("iata"),
            pl.col("name"),
            pl.col("latitude_deg").alias("lat"),
            pl.col("longitude_deg").alias("lon"),
            pl.col("type").replace_strict(SIZE_BY_TYPE).alias("size"),
            pl.col("iso_country").alias("country"),
        )
        .drop_nulls(["lat", "lon"])
        .unique(subset=["iata"], keep="first")
        .sort("iata")
    )
    _atomic_write(out, lambda tmp: df.write_parquet(tmp))
    return df
