import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from watcher.config import DEFAULT_PATH, SEARCH_ID, SEARCHES_LOCK, read_saved_searches, write_saved_searches

HOST = "usedcars.volkswagen.co.uk"
_SEARCH_ROOT = "/en/vehicle_search"
_PAGE = re.compile(r"^page\d+$")
_NOT_FILTERS = {"view", "search", "MANUFACTURER_LST"}
_RESERVED_IDS = {"debug"}


class SearchError(ValueError):
    pass


def parse_search_url(url: str) -> tuple[str, dict]:
    """Split a pasted Volkswagen search address into the path and query the scraper requests."""
    text = (url or "").strip()
    if not text:
        raise SearchError("Paste the address of a search on usedcars.volkswagen.co.uk.")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or host not in (HOST, "www." + HOST):
        raise SearchError(f"The address must be a search on {HOST}.")

    segments = [segment for segment in parts.path.split("/") if segment]
    if segments and _PAGE.match(segments[-1]):
        segments.pop()
    root = [segment for segment in _SEARCH_ROOT.split("/") if segment]
    if segments[: len(root)] != root:
        raise SearchError("That is not a search results page. Run the search on the Volkswagen site and copy the address from the results list.")
    rest = segments[len(root) :]
    if len(rest) > 2:
        raise SearchError("That looks like a single car's page. Copy the address of the results list instead.")
    if len(rest) == 1:
        raise SearchError("That is not a search results page. Run the search on the Volkswagen site and copy the address from the results list.")
    path = "/" + "/".join(segments) if rest else DEFAULT_PATH

    query: dict[str, str | list[str]] = {}
    for key, value in parse_qsl(parts.query):
        if key in query:
            existing = query[key]
            query[key] = (existing if isinstance(existing, list) else [existing]) + [value]
        else:
            query[key] = value
    if path == DEFAULT_PATH and not set(query) - _NOT_FILTERS:
        raise SearchError("That search has no filters, so it would watch every used Volkswagen. Pick a model, colour, or other filter first.")
    return path, query


def add_search(cfg: dict, url: str, name: str = "") -> dict:
    path, query = parse_search_url(url)
    name = " ".join((name or "").split())[:80] or _default_name(query)
    with SEARCHES_LOCK:
        entries = read_saved_searches(cfg["data_dir"])
        taken = {search["id"] for search in cfg["searches"]} | {entry.get("id") for entry in entries} | _RESERVED_IDS
        root = Path(cfg["data_dir"])
        search_id = _unique_id(name, lambda candidate: candidate in taken or (root / candidate).exists())
        entry = {
            "id": search_id,
            "name": name,
            "url": url.strip(),
            "path": path,
            "query": query,
            "added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        entries.append(entry)
        write_saved_searches(cfg["data_dir"], entries)
    return entry


def remove_search(cfg: dict, search_id: str) -> bool:
    with SEARCHES_LOCK:
        entries = read_saved_searches(cfg["data_dir"])
        kept = [entry for entry in entries if entry.get("id") != search_id]
        if len(kept) == len(entries):
            return False
        write_saved_searches(cfg["data_dir"], kept)
    return True


def _unique_id(name: str, taken) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-") or "search"
    candidate = base
    number = 2
    while taken(candidate) or not SEARCH_ID.fullmatch(candidate):
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def _default_name(query: dict) -> str:
    def single(key: str) -> str:
        value = query.get(key)
        if not isinstance(value, str) or "||" in value:
            return ""
        return value

    colour = single("BODY_BASE_COLOR_LST").replace("_", " ").title()
    model = single("MODEL_TYPE_LST")
    if model.startswith("VOLKSWAGEN_"):
        model = model[len("VOLKSWAGEN_") :]
    model = model.replace("_", " ").title()
    trim = single("TRIM_STR")
    return " ".join(part for part in (colour, model, trim) if part) or "VW search"
