_DETAIL_FIELDS = (
    ("colour", "Colour"),
    ("trim", "Trim"),
    ("transmission", "Gearbox"),
    ("fuel", "Fuel"),
    ("reg_month", "Reg month"),
    ("reg_year", "Year"),
)

CHANGE_KEYS = ("added", "removed", "price_down", "price_up", "mileage", "location", "owners", "details")


def empty_diff() -> dict:
    return {
        "has_previous": False,
        "previous_scraped_at": None,
        "previous_count": None,
        "previous_average_price": None,
        "added": [],
        "removed": [],
        "price_down": [],
        "price_up": [],
        "mileage": [],
        "location": [],
        "owners": [],
        "details": [],
    }


def build_diff(previous: dict | None, vehicles: list[dict]) -> dict:
    if not previous:
        return empty_diff()

    diff = empty_diff()
    diff["has_previous"] = True
    diff["previous_scraped_at"] = previous.get("scraped_at")
    summary = previous.get("summary") or {}
    diff["previous_count"] = summary.get("count")
    diff["previous_average_price"] = summary.get("average_price")

    before = {vehicle["key"]: vehicle for vehicle in previous.get("vehicles") or []}
    after = {vehicle["key"]: vehicle for vehicle in vehicles}

    diff["added"] = [after[key] for key in after if key not in before]
    diff["removed"] = [before[key] for key in before if key not in after]
    diff["added"].sort(key=_price_sort)
    diff["removed"].sort(key=_price_sort)

    for key in after.keys() & before.keys():
        current = after[key]
        old = before[key]
        _price_change(diff, old, current)
        _number_change(diff, "mileage", old, current)
        _text_change(diff, "location", "location", old, current)
        _text_change(diff, "owners", "previous_owners", old, current)
        detail_changes = []
        for field, label in _DETAIL_FIELDS:
            if (old.get(field) or "") != (current.get(field) or ""):
                detail_changes.append({"field": label, "before": old.get(field) or "", "after": current.get(field) or ""})
        if detail_changes:
            diff["details"].append({"vehicle": current, "changes": detail_changes})

    diff["price_down"].sort(key=lambda item: item["delta"])
    diff["price_up"].sort(key=lambda item: -item["delta"])
    return diff


def has_changes(diff: dict) -> bool:
    return bool(diff.get("has_previous")) and any(diff.get(key) for key in CHANGE_KEYS)


def summarise(vehicles: list[dict]) -> dict:
    priced = [vehicle["price"] for vehicle in vehicles if vehicle.get("price") is not None]
    return {
        "count": len(vehicles),
        "average_price": round(sum(priced) / len(priced)) if priced else None,
        "unknown_options": sum(1 for vehicle in vehicles if vehicle.get("options") == "UNKNOWN"),
        "unknown_owners": sum(1 for vehicle in vehicles if vehicle.get("previous_owners") == "UNKNOWN"),
    }


def _price_change(diff: dict, old: dict, current: dict) -> None:
    before = old.get("price")
    after = current.get("price")
    if before is None or after is None or before == after:
        return
    bucket = "price_down" if after < before else "price_up"
    diff[bucket].append({"vehicle": current, "before": before, "after": after, "delta": after - before})


def _number_change(diff: dict, bucket: str, old: dict, current: dict) -> None:
    before = old.get(bucket)
    after = current.get(bucket)
    if before is None or after is None or before == after:
        return
    diff[bucket].append({"vehicle": current, "before": before, "after": after, "delta": after - before})


def _text_change(diff: dict, bucket: str, field: str, old: dict, current: dict) -> None:
    before = old.get(field) or ""
    after = current.get(field) or ""
    if before != after:
        diff[bucket].append({"vehicle": current, "before": before, "after": after})


def _price_sort(vehicle: dict):
    return (vehicle.get("price") is None, vehicle.get("price") or 0, vehicle.get("plate") or "")
