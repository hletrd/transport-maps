"""OurAirports -> airports with scheduled passenger service."""

import httpx
import polars as pl

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

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
    config.ensure_dirs()
    cached = config.CACHE / "ourairports.csv"
    if not cached.exists():
        r = httpx.get(AIRPORTS_URL, follow_redirects=True, timeout=120)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached.read_bytes()


def scheduled_airports() -> pl.DataFrame:
    out = config.BUILD / "airports.parquet"
    if out.exists():
        return pl.read_parquet(out)

    raw = pl.read_csv(_download(), infer_schema_length=10_000)
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
