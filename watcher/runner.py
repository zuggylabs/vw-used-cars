import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from watcher.config import load_config
from watcher.diff import build_diff, summarise
from watcher.report import render_run
from watcher.options import OptionsStore
from watcher.scrape import ScrapeError, fetch_search, normalise_vehicles, search_page_url
from watcher.store import Store

log = logging.getLogger(__name__)


class Runner:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.queued: set[str] = set()
        self.errors: dict[str, str] = {}
        self.last_finished: str | None = None

    @property
    def busy(self) -> bool:
        return self.running or bool(self.queued)

    def queue(self, search_id: str) -> None:
        """Scrape one search in the background, after any run already in progress."""
        self.queued.add(search_id)

        def work():
            try:
                self.run(only=search_id, wait=True)
            finally:
                self.queued.discard(search_id)

        threading.Thread(target=work, name=f"scrape-{search_id}", daemon=True).start()

    def run(self, only: str | None = None, wait: bool = False) -> bool:
        """Scrape every search, or just the search with id `only`. With wait, queue behind a run in progress."""
        if not self._lock.acquire(blocking=wait):
            log.info("A scrape is already running")
            return False
        self.running = True
        if only is not None:
            self.queued.discard(only)
        if only is None:
            self.errors = {}
        else:
            self.errors.pop(only, None)
            self.errors.pop("run", None)
        try:
            self._run(only)
        except Exception as exc:
            log.exception("Scrape run failed")
            self.errors["run"] = str(exc) or exc.__class__.__name__
        finally:
            self.running = False
            self._lock.release()
        return True

    def _run(self, only: str | None) -> None:
        cfg = load_config()
        searches = [search for search in cfg["searches"] if only is None or search["id"] == only]
        if not searches:
            log.info("No searches to scrape")
            return
        store = Store(cfg["data_dir"])
        options = {identity: car["text"] for identity, car in OptionsStore(cfg["data_dir"]).summaries().items()}
        started = datetime.now(ZoneInfo(cfg["timezone"]))
        for search in searches:
            try:
                self._one(cfg, store, options, search, started)
            except (ScrapeError, OSError) as exc:
                log.error("%s failed: %s", search["name"], exc)
                self.errors[search["id"]] = str(exc)
            except Exception as exc:
                log.exception("%s failed", search["name"])
                self.errors[search["id"]] = str(exc) or exc.__class__.__name__
        self.last_finished = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")

    def _one(self, cfg: dict, store: Store, options: dict, search: dict, started: datetime) -> None:
        raw, total = fetch_search(search, cfg)
        vehicles = normalise_vehicles(raw, search, options)
        previous = store.latest(search["id"])
        run = {
            "search_id": search["id"],
            "search_name": search["name"],
            "scraped_at": started.isoformat(timespec="seconds"),
            "search_url": search_page_url(search),
            "listed_on_site": total,
            "summary": summarise(vehicles),
            "vehicles": vehicles,
            "diff": build_diff(previous, vehicles),
        }
        store.save(run)
        store.write_history(search["id"])
        log.info("\n%s", render_run(run).rstrip())
