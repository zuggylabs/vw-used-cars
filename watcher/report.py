from datetime import datetime

from watcher.diff import build_diff, has_changes


def render_run(run: dict) -> str:
    summary = run["summary"]
    diff = run["diff"]
    lines = [
        run["search_name"],
        _when(run["scraped_at"]),
        _stock_line(summary, diff),
        "",
    ]
    if not diff["has_previous"]:
        lines.append("First snapshot. The next run will show what changed.")
        lines.append("")
        lines.extend(_vehicle_line(vehicle) for vehicle in run["vehicles"])
    elif not has_changes(diff):
        lines.append(f"No changes since {_when(diff['previous_scraped_at'])}.")
    else:
        lines.extend(_section("Price reduced", diff["price_down"], _price_line))
        lines.extend(_section("New", diff["added"], _vehicle_line))
        lines.extend(_section("Removed (no longer listed)", diff["removed"], _vehicle_line))
        lines.extend(_section("Price increased", diff["price_up"], _price_line))
        lines.extend(_section("Mileage", diff["mileage"], _mileage_line))
        lines.extend(_section("Dealer", diff["location"], _text_line))
        lines.extend(_section("Previous owners", diff["owners"], _text_line))
        lines.extend(_section("Other details", diff["details"], _detail_line))

    if summary["unknown_options"]:
        lines.extend(["", f"Options not checked yet: {summary['unknown_options']}"])
        for vehicle in run["vehicles"]:
            if vehicle.get("options") == "UNKNOWN":
                lines.append(f"- {vehicle['plate'] or vehicle['id']}  {vehicle['title']}")
    if summary["unknown_owners"]:
        lines.append(f"Previous owners not shown: {summary['unknown_owners']}")
    return "\n".join(lines).rstrip() + "\n"


def render_history(runs: list[dict]) -> str:
    events: dict[str, list[str]] = {}
    previous = None
    for run in runs:
        if previous is not None:
            diff = build_diff(previous, run["vehicles"])
            stamp = _stamp(run["scraped_at"])
            for vehicle in diff["added"]:
                _add(events, vehicle, f"{stamp}: Added")
            for vehicle in diff["removed"]:
                _add(events, vehicle, f"{stamp}: Removed")
            for item in diff["price_down"] + diff["price_up"]:
                _add(events, item["vehicle"], f"{stamp}: {_gbp(item['before'])} -> {_gbp(item['after'])}")
            for item in diff["mileage"]:
                _add(events, item["vehicle"], f"{stamp}: Mileage {_miles(item['before'])} -> {_miles(item['after'])}")
            for item in diff["location"]:
                _add(events, item["vehicle"], f"{stamp}: {item['before']} -> {item['after']}")
            for item in diff["owners"]:
                _add(events, item["vehicle"], f"{stamp}: Owners {item['before']} -> {item['after']}")
            for item in diff["details"]:
                for change in item["changes"]:
                    _add(
                        events,
                        item["vehicle"],
                        f"{stamp}: {change['field']} {change['before'] or 'blank'} -> {change['after'] or 'blank'}",
                    )
        previous = run

    blocks = []
    for plate in sorted(events):
        blocks.append("Plate: " + plate + "\n" + "\n".join(events[plate]))
    if not blocks:
        return "No changes recorded yet.\n"
    return "\n\n\n".join(blocks) + "\n"


def _section(title: str, items: list, render) -> list[str]:
    if not items:
        return []
    lines = [title]
    lines.extend(render(item) for item in items)
    lines.append("")
    return lines


def _vehicle_line(vehicle: dict) -> str:
    plate = vehicle.get("plate") or vehicle.get("id")
    bits = [plate, _gbp(vehicle.get("price")), f"{_miles(vehicle.get('mileage'))} mi"]
    if vehicle.get("reg_year"):
        bits.append(str(vehicle["reg_year"]))
    if vehicle.get("location"):
        bits.append(vehicle["location"])
    text = "  ".join(bits)
    if vehicle.get("title"):
        text += f"\n  {vehicle['title']}"
    if vehicle.get("url"):
        text += f"\n  {vehicle['url']}"
    return text


def _price_line(item: dict) -> str:
    vehicle = item["vehicle"]
    delta = int(item["delta"])
    sign = "-" if delta < 0 else "+"
    text = f"{vehicle.get('plate') or vehicle.get('id')}  {_gbp(item['before'])} -> {_gbp(item['after'])} ({sign}£{abs(delta):,})"
    if vehicle.get("title"):
        text += f"\n  {vehicle['title']}"
    if vehicle.get("url"):
        text += f"\n  {vehicle['url']}"
    return text


def _mileage_line(item: dict) -> str:
    vehicle = item["vehicle"]
    return f"{vehicle.get('plate') or vehicle.get('id')}  {_miles(item['before'])} -> {_miles(item['after'])} mi"


def _text_line(item: dict) -> str:
    vehicle = item["vehicle"]
    return f"{vehicle.get('plate') or vehicle.get('id')}  {item['before'] or 'blank'} -> {item['after'] or 'blank'}"


def _detail_line(item: dict) -> str:
    vehicle = item["vehicle"]
    plate = vehicle.get("plate") or vehicle.get("id")
    parts = [f"{change['field']} {change['before'] or 'blank'} -> {change['after'] or 'blank'}" for change in item["changes"]]
    return plate + "  " + "; ".join(parts)


def _stock_line(summary: dict, diff: dict) -> str:
    line = f"{summary['count']} cars, average {_gbp(summary['average_price'])}"
    if diff.get("has_previous") and diff.get("previous_count") is not None:
        line += f" (was {diff['previous_count']}, average {_gbp(diff.get('previous_average_price'))})"
    return line


def _add(events: dict[str, list[str]], vehicle: dict, line: str) -> None:
    events.setdefault(vehicle.get("plate") or vehicle.get("id") or "UNKNOWN", []).append(line)


def _gbp(value) -> str:
    if value is None:
        return "unknown"
    return f"£{int(value):,}"


def _miles(value) -> str:
    if value is None:
        return "unknown"
    return f"{int(value):,}"


def _when(value: str | None) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value)
    return f"{parsed.day} {parsed.strftime('%b %Y, %H:%M')}"


def _stamp(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y%m%d")
