import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlencode

import requests

from watcher.config import plate_key

log = logging.getLogger(__name__)

BASE = "https://usedcars.volkswagen.co.uk"
_MARKER = "let vehicles = JSON.parse("
_TOTAL = re.compile(r"of\s+([\d,]+)\s+results", re.I)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class ScrapeError(RuntimeError):
    pass


def fetch_search(search: dict, cfg: dict) -> tuple[list[dict], int | None]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    seen: set[str] = set()
    collected: list[dict] = []
    total: int | None = None
    page_size: int | None = None
    last_html = ""
    max_pages = cfg["max_pages"]

    for page in range(1, max_pages + 1):
        url = _page_url(page, search)
        last_html = _get(session, url)
        found = _parse_total(last_html)
        if found is not None:
            total = found
        batch = _parse_vehicles(last_html)
        if batch is None:
            _save_debug(cfg, search["id"], last_html)
            raise ScrapeError(f"{search['name']}: page {page} did not contain the vehicle list")
        if page == 1 and not batch:
            return [], 0
        if page_size is None:
            page_size = len(batch)
        fresh = []
        for item in batch:
            identity = item.get("ID") or item.get("LEGACY_CHIFFRE_STR") or item.get("LICENSE_NUMBER_STR")
            if not identity or identity in seen:
                continue
            if not (item.get("LICENSE_NUMBER_STR") or item.get("MODEL_TEXT_STR")):
                continue
            seen.add(identity)
            fresh.append(item)
        collected.extend(fresh)
        log.info("%s page %s: %s new cars (%s/%s)", search["id"], page, len(fresh), len(collected), total if total is not None else "?")
        if not fresh or (total is not None and len(collected) >= total) or (page_size and len(batch) < page_size):
            break
        time.sleep(cfg["page_delay_seconds"])
    else:
        _save_debug(cfg, search["id"], last_html)
        raise ScrapeError(f"{search['name']}: stopped after {max_pages} pages with {len(collected)} of {total} cars")

    if total is not None and len(collected) < total:
        _save_debug(cfg, search["id"], last_html)
        raise ScrapeError(f"{search['name']}: the site listed {total} cars but only {len(collected)} could be read")
    return collected, total


def normalise_vehicles(raw_vehicles: list[dict], search: dict, options: dict[str, str]) -> list[dict]:
    vehicles = []
    for raw in raw_vehicles:
        vehicle = _normalise(raw, options)
        if vehicle is None:
            continue
        if vehicle["plate"] and vehicle["plate"] in search["ignore_plates"]:
            continue
        if search["doors"] is not None and vehicle["doors"] not in (None, search["doors"]):
            continue
        vehicles.append(vehicle)

    counts: dict[str, int] = {}
    for vehicle in vehicles:
        base = vehicle["plate"] or vehicle["id"]
        counts[base] = counts.get(base, 0) + 1
    for vehicle in vehicles:
        base = vehicle["plate"] or vehicle["id"]
        vehicle["key"] = base if counts[base] == 1 else f"{base}:{vehicle['id']}"

    vehicles.sort(key=lambda vehicle: (vehicle["price"] is None, vehicle["price"] or 0, vehicle["plate"], vehicle["id"]))
    return vehicles


def search_page_url(search: dict) -> str:
    return _page_url(1, search)


def _page_url(page: int, search: dict) -> str:
    path = search["path"].rstrip("/")
    if page > 1:
        path += f"/page{page}"
    query = urlencode({key: _site_value(value) for key, value in search["query"].items()}, doseq=True, safe="|")
    return BASE + path + (f"?{query}" if query else "")


def _site_value(value):
    # The site URL-decodes filter values a second time, and a bare apostrophe (as in the trim
    # "R '20 Years'") makes it ignore that value and every || value after it.
    if isinstance(value, list):
        return [_site_value(item) for item in value]
    return str(value).replace("'", "%27")


def _get(session: requests.Session, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=(10, 60))
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise ScrapeError(f"Could not download {url}") from last_error


def _parse_total(html: str) -> int | None:
    match = _TOTAL.search(html)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _parse_vehicles(html: str) -> list[dict] | None:
    """Return the vehicle list, or None when the page has no vehicle data at all."""
    raw = _extract_vehicle_json(html)
    if raw is None:
        return None
    # Dealer text sometimes contains an apostrophe escaped for JavaScript, not JSON.
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(raw.replace("\\'", "'"))
        except json.JSONDecodeError as exc:
            raise ScrapeError(f"Vehicle data on the page could not be parsed ({exc})") from exc
    if not isinstance(parsed, list):
        raise ScrapeError("Vehicle data on the page was not a list")
    return [item for item in parsed if isinstance(item, dict)]


def _extract_vehicle_json(html: str) -> str | None:
    """Cut out the JSON array. Titles can contain apostrophes, so the JavaScript quotes are not a safe boundary."""
    start = html.find(_MARKER)
    if start < 0:
        return None
    index = html.find("[", start)
    if index < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(index, len(html)):
        char = html[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return html[index : pos + 1]
    return None


def _normalise(raw: dict, options: dict[str, str]) -> dict | None:
    plate = plate_key(raw.get("LICENSE_NUMBER_STR") or "")
    vehicle_id = str(raw.get("ID") or raw.get("LEGACY_CHIFFRE_STR") or "").strip()
    if not plate and not vehicle_id:
        return None

    manufacturer = (raw.get("MANUFACTURER_LST") or "Volkswagen").strip()
    model = (raw.get("MODEL_TEXT_STR") or "").strip()
    sub_model = (raw.get("SUB_MODEL_TEXT_STR") or "").strip()
    title = " ".join(part for part in (manufacturer, model, sub_model) if part)
    reg_month, reg_year = _registration(raw.get("INITIAL_REGISTRATION_DTE") or "")
    dealer = (raw.get("POOL_NAME1_STR") or "").strip()
    city = (raw.get("POOL_CITY_STR") or "").strip()
    if city and city.lower() not in dealer.lower():
        location = f"{dealer} ({city})" if dealer else city
    else:
        location = dealer or city

    return {
        "key": plate or vehicle_id,
        "plate": plate,
        "id": vehicle_id,
        "title": title,
        "description": _description(raw),
        "price": _as_int(raw.get("PRICE_RETAIL_CUR_FLT")),
        "mileage": _as_int(raw.get("MILEAGE_MIL_INT")),
        "options": options.get(plate or vehicle_id, "UNKNOWN"),
        "reg_month": reg_month,
        "reg_year": reg_year,
        "previous_owners": _owners(raw.get("PREVIOUS_OWNER_STR")),
        "location": location,
        "url": _listing_url(manufacturer, model, sub_model, vehicle_id),
        "colour": (raw.get("BODY_COLOR_STR") or raw.get("BODY_BASE_COLOR_LST") or "").strip(),
        "trim": (raw.get("TRIM_STR") or "").strip(),
        "transmission": (raw.get("TRANSMISSION_LST") or "").strip(),
        "fuel": (raw.get("FUEL_TYPE_LST") or "").strip(),
        "doors": _as_int(raw.get("NUMBER_OF_DOORS_INT")),
    }


def _description(raw: dict) -> str:
    colour = (raw.get("BODY_COLOR_STR") or "").strip()
    interior = " ".join(
        part
        for part in (
            (raw.get("INTERIOR_COLOR_STR") or "").strip(),
            (raw.get("INTERIOR_FITTINGS_STR") or "").strip(),
        )
        if part
    )
    if colour and interior:
        return f"Finished in {colour} with {interior} interior"
    if colour:
        return f"Finished in {colour}"
    return interior


def _owners(value) -> str:
    text = str(value or "").strip()
    if text in {"", "-", "–"}:
        return "UNKNOWN"
    return text


def _registration(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "", ""
    return _MONTHS[parsed.month - 1], str(parsed.year)


def _listing_url(manufacturer: str, model: str, sub_model: str, vehicle_id: str) -> str:
    if not vehicle_id:
        return ""
    return (
        f"{BASE}/en/vehicle_search/{_slug(manufacturer)}/{_slug(model or 'car')}/"
        f"{_slug(sub_model or 'vehicle')}-{vehicle_id.lower()}"
    )


def _slug(text: str) -> str:
    # Match the site: lowercase first, then turn a pound sign into GBP so it stays uppercase.
    text = text.lower().replace("£", "GBP").replace("'", "").replace("’", "").replace(".", "")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text)
    return text.strip("-") or "vehicle"


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def _save_debug(cfg: dict, search_id: str, html: str) -> None:
    if not html:
        return
    from pathlib import Path

    path = Path(cfg["data_dir"]) / "debug" / f"{search_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    log.error("Saved the failed page to %s", path)
