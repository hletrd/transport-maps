import json
from pathlib import Path


def write_bands(path: Path, feature_collection: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection), encoding="utf-8")
