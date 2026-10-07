import re
import threading
from datetime import datetime

from flask import Flask, abort, redirect, render_template, request, url_for

from watcher.config import SEARCH_ID, load_config
from watcher.diff import CHANGE_KEYS
from watcher.options import OptionsStore
from watcher.scrape import search_page_url
from watcher.searches import SearchError, add_search, remove_search
from watcher.store import Store, car_identity

_STAMP = re.compile(r"^[0-9]{8}T[0-9]{6}$")
_CAR = re.compile(r"[A-Za-z0-9]{1,24}")
_LABELS = (
    ("price_down", "price cut", "price cuts"),
    ("added", "new car", "new cars"),
    ("removed", "removed", "removed"),
    ("price_up", "price rise", "price rises"),
    ("mileage", "mileage change", "mileage changes"),
    ("location", "dealer change", "dealer changes"),
    ("owners", "owner change", "owner changes"),
    ("details", "detail change", "detail changes"),
)


def create_app(runner, scheduler=None) -> Flask:
    app = Flask(__name__)

    @app.template_filter("gbp")
    def gbp(value):
        if value is None:
            return "—"
        return f"£{int(value):,}"

    @app.template_filter("miles")
    def miles(value):
        if value is None:
            return "—"
        return f"{int(value):,}"

    @app.template_filter("gbpdelta")
    def gbpdelta(value):
        number = int(value)
        sign = "−" if number < 0 else "+"
        return f"{sign}£{abs(number):,}"

    @app.template_filter("when")
    def when(value):
        if not value:
            return ""
        parsed = datetime.fromisoformat(value)
        return f"{parsed.day} {parsed.strftime('%b %Y, %H:%M')}"

    @app.get("/health")
    def health():
        return {"ok": True, "running": runner.busy}

    @app.get("/")
    def index():
        return _render_index(runner, scheduler)

    @app.post("/run")
    def run_now():
        threading.Thread(target=runner.run, name="manual-scrape", daemon=True).start()
        return redirect(url_for("index"))

    @app.post("/searches")
    def create_search():
        url = request.form.get("url", "")
        name = request.form.get("name", "")
        try:
            entry = add_search(_cfg(), url, name)
        except SearchError as exc:
            return _render_index(runner, scheduler, form={"url": url, "name": name}, form_error=str(exc)), 400
        runner.queue(entry["id"])
        return redirect(url_for("search_latest", search_id=entry["id"]))

    @app.post("/search/<search_id>/remove")
    def delete_search(search_id):
        cfg = _require_search(search_id)
        if not remove_search(cfg, search_id):
            abort(404)
        runner.errors.pop(search_id, None)
        return redirect(url_for("index"))

    @app.get("/search/<search_id>")
    def search_latest(search_id):
        return _render_search(search_id, None, runner)

    @app.get("/search/<search_id>/<stamp>")
    def search_at(search_id, stamp):
        if not _STAMP.fullmatch(stamp):
            abort(404)
        return _render_search(search_id, stamp, runner)

    @app.post("/options")
    def save_options():
        cfg = _cfg()
        names = {key[len("option-") :]: value for key, value in request.form.items() if key.startswith("option-")}
        _options(cfg).save_list(names, [request.form.get("new", "")])
        return redirect(url_for("index") + "#options")

    @app.get("/car/<identity>")
    def car_options(identity):
        cfg = _cfg()
        if not _CAR.fullmatch(identity):
            abort(404)
        store = _options(cfg)
        return render_template(
            "car.html",
            identity=identity,
            vehicle=_find_car(cfg, identity),
            options=store.options(),
            car=store.car(identity),
            back=_safe_back(request.args.get("back")),
            running=runner.busy,
        )

    @app.post("/car/<identity>")
    def save_car_options(identity):
        cfg = _cfg()
        if not _CAR.fullmatch(identity):
            abort(404)
        states = {key[len("state-") :]: value for key, value in request.form.items() if key.startswith("state-")}
        _options(cfg).set_car(identity, states)
        return redirect(_safe_back(request.form.get("back")) or url_for("index"))

    @app.post("/search/<search_id>/hide")
    def hide_car(search_id):
        cfg = _require_search(search_id)
        store = Store(cfg["data_dir"])
        stamp = _form_stamp(store, search_id)
        run = store.get(search_id, stamp) if stamp else None
        identity = request.form.get("identity", "")
        cars = ((run or {}).get("vehicles") or []) + ((run or {}).get("diff") or {}).get("removed", [])
        vehicle = next((car for car in cars if identity and car_identity(car) == identity), None)
        if vehicle is None:
            abort(404)
        store.hide(search_id, vehicle, datetime.now().astimezone().isoformat(timespec="seconds"))
        return _back(search_id, stamp, store)

    @app.post("/search/<search_id>/unhide")
    def unhide_car(search_id):
        cfg = _require_search(search_id)
        store = Store(cfg["data_dir"])
        store.unhide(search_id, request.form.get("identity", ""))
        return _back(search_id, _form_stamp(store, search_id), store)

    @app.get("/search/<search_id>/history")
    def history(search_id):
        cfg = _require_search(search_id)
        path = Store(cfg["data_dir"]).root / search_id / "history.txt"
        if not path.is_file():
            abort(404)
        return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}

    return app


def _render_index(runner, scheduler, form: dict | None = None, form_error: str | None = None):
    cfg = _cfg()
    store = Store(cfg["data_dir"])
    cards = []
    for search in cfg["searches"]:
        run = store.latest(search["id"])
        hidden_ids = {entry["identity"] for entry in store.hidden(search["id"])}
        cards.append(
            {
                "search": search,
                "run": run,
                "hidden": sum(1 for vehicle in (run or {}).get("vehicles") or [] if car_identity(vehicle) in hidden_ids),
                "labels": _change_labels(run),
                "error": runner.errors.get(search["id"]),
                "queued": search["id"] in runner.queued,
            }
        )
    return render_template(
        "index.html",
        cards=cards,
        running=runner.busy,
        run_error=runner.errors.get("run"),
        next_run=_next_run(scheduler),
        timezone=cfg["timezone"],
        form=form or {"url": "", "name": ""},
        form_error=form_error,
        options=_options(cfg).options(),
    )


def _render_search(search_id: str, stamp: str | None, runner):
    cfg = _require_search(search_id)
    search = next(item for item in cfg["searches"] if item["id"] == search_id)
    store = Store(cfg["data_dir"])
    stamps = store.stamps(search_id)
    if stamp is None:
        stamp = stamps[-1] if stamps else None
    run = store.get(search_id, stamp) if stamp else None
    if stamp and run is None:
        abort(404)
    earlier = []
    for old_stamp in reversed(stamps):
        old = store.get(search_id, old_stamp)
        if not old:
            continue
        diff = old["diff"]
        changes = sum(len(diff.get(key) or []) for key in CHANGE_KEYS) if diff.get("has_previous") else None
        earlier.append(
            {
                "stamp": old_stamp,
                "scraped_at": old["scraped_at"],
                "count": old["summary"]["count"],
                "changes": changes,
                "current": old_stamp == stamp,
            }
        )
    hidden_entries = store.hidden(search_id)
    hidden_ids = {entry["identity"] for entry in hidden_entries}
    vehicles = (run or {}).get("vehicles") or []
    listed = {car_identity(vehicle): vehicle for vehicle in vehicles}
    visible = [vehicle for vehicle in vehicles if car_identity(vehicle) not in hidden_ids]
    hidden_rows = [
        {"entry": entry, "vehicle": listed.get(entry["identity"])}
        for entry in sorted(hidden_entries, key=lambda entry: entry["hidden_at"], reverse=True)
    ]
    options = _options(cfg)
    car_options = options.summaries()
    unchecked = sum(1 for vehicle in visible if car_identity(vehicle) not in car_options)
    return render_template(
        "search.html",
        search=search,
        run=run,
        stamp=stamp,
        earlier=earlier,
        visible=visible,
        hidden_ids=hidden_ids,
        hidden_rows=hidden_rows,
        hidden_listed=len(vehicles) - len(visible),
        option_count=len(options.options()),
        car_options=car_options,
        unchecked=unchecked,
        back=request.path,
        is_latest=bool(stamps) and stamp == stamps[-1],
        search_url=search_page_url(search),
        running=runner.busy,
        error=runner.errors.get(search_id),
    )


def _options(cfg: dict) -> OptionsStore:
    return OptionsStore(cfg["data_dir"])


def _find_car(cfg: dict, identity: str) -> dict | None:
    store = Store(cfg["data_dir"])
    for search in cfg["searches"]:
        run = store.latest(search["id"])
        for vehicle in (run or {}).get("vehicles") or []:
            if car_identity(vehicle) == identity:
                return vehicle
    return None


def _safe_back(value: str | None) -> str | None:
    if value and value.startswith("/search/") and "//" not in value and "\\" not in value:
        return value
    return None


def _form_stamp(store: Store, search_id: str) -> str | None:
    stamp = request.form.get("stamp", "")
    if _STAMP.fullmatch(stamp):
        return stamp
    stamps = store.stamps(search_id)
    return stamps[-1] if stamps else None


def _back(search_id: str, stamp: str | None, store: Store):
    section = request.form.get("section", "")
    anchor = f"#{section}" if section in ("changes", "cars", "hidden") else ""
    stamps = store.stamps(search_id)
    if stamp and stamps and stamp != stamps[-1]:
        return redirect(url_for("search_at", search_id=search_id, stamp=stamp) + anchor)
    return redirect(url_for("search_latest", search_id=search_id) + anchor)


def _require_search(search_id: str) -> dict:
    if not SEARCH_ID.fullmatch(search_id):
        abort(404)
    cfg = _cfg()
    if search_id not in {search["id"] for search in cfg["searches"]}:
        abort(404)
    return cfg


def _cfg() -> dict:
    try:
        return load_config()
    except (OSError, ValueError) as exc:
        abort(500, description=str(exc))


def _change_labels(run: dict | None) -> list[tuple[str, str]]:
    if not run:
        return []
    diff = run["diff"]
    if not diff["has_previous"]:
        return [("first", "First snapshot")]
    labels = []
    for key, one, many in _LABELS:
        count = len(diff.get(key) or [])
        if count == 1:
            labels.append((key, f"1 {one}"))
        elif count:
            labels.append((key, f"{count} {many}"))
    return labels or [("none", "No changes")]


def _next_run(scheduler) -> str | None:
    if scheduler is None:
        return None
    job = scheduler.get_job("scrape")
    if not job or not job.next_run_time:
        return None
    when = job.next_run_time
    return f"{when.strftime('%H:%M')}, {when.strftime('%A')} {when.day} {when.strftime('%B')}"
