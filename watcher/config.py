import json
import os
import re
import threading
from pathlib import Path

import yaml

_PLATE = re.compile(r"[^A-Z0-9]")
SEARCH_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")
DEFAULT_PATH = "/en/vehicle_search/volkswagen/all-models"
USER_SEARCHES_FILE = "searches.json"
SEARCHES_LOCK = threading.RLock()


def plate_key(value: str) -> str:
    return _PLATE.sub("", (value or "").upper())


def load_config() -> dict:
    path = os.environ.get("CONFIG_PATH", "config.yaml")
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    data_dir = os.environ.get("DATA_DIR") or raw.get("data_dir") or "data"

    searches = []
    seen = set()
    for entry in read_saved_searches(data_dir):
        search = _search(entry)
        if search["id"] in seen:
            raise ValueError(f"Search id {search['id']!r} appears twice in {USER_SEARCHES_FILE}")
        seen.add(search["id"])
        searches.append(search)

    return {
        "schedule": str(raw.get("schedule") or "0 8 * * *"),
        "timezone": str(raw.get("timezone") or "Europe/London"),
        "run_on_startup": bool(raw.get("run_on_startup", True)),
        "page_delay_seconds": float(raw.get("page_delay_seconds", 0.5)),
        "max_pages": int(raw.get("max_pages", 30)),
        "data_dir": data_dir,
        "searches": searches,
    }


def read_saved_searches(data_dir: str) -> list[dict]:
    data = _read_file(data_dir)
    return list((data or {}).get("searches") or [])


def write_saved_searches(data_dir: str, entries: list[dict]) -> None:
    path = Path(data_dir) / USER_SEARCHES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    payload = {"searches": entries}
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_file(data_dir: str) -> dict | None:
    path = Path(data_dir) / USER_SEARCHES_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} could not be read ({exc})") from exc


def _search(entry: dict) -> dict:
    search_id = str(entry.get("id") or "").strip()
    if not SEARCH_ID.fullmatch(search_id):
        raise ValueError(f"Search id {search_id!r} must be a short lowercase slug")
    path = str(entry.get("path") or DEFAULT_PATH)
    query = {key: value for key, value in (entry.get("query") or {}).items() if value is not None and str(value) != ""}
    if not query and path == DEFAULT_PATH:
        raise ValueError(f"Search {search_id} has no query")
    doors = entry.get("doors")
    return {
        "id": search_id,
        "name": entry.get("name") or search_id,
        "path": path,
        "doors": int(doors) if doors not in (None, "") else None,
        "ignore_plates": {plate_key(p) for p in (entry.get("ignore_plates") or []) if plate_key(p)},
        "query": query,
    }
