import json
import threading
from datetime import datetime
from pathlib import Path

from watcher.report import render_history, render_run

_STAMP = "%Y%m%dT%H%M%S"
_HIDDEN_LOCK = threading.Lock()


def car_identity(vehicle: dict) -> str:
    return vehicle.get("plate") or vehicle.get("id") or ""


class Store:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)

    def save(self, run: dict) -> Path:
        folder = self.root / run["search_id"]
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromisoformat(run["scraped_at"]).strftime(_STAMP)
        path = folder / f"{stamp}.json"
        path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "latest.txt").write_text(render_run(run), encoding="utf-8")
        return path

    def write_history(self, search_id: str) -> None:
        text = render_history(self.all_runs(search_id))
        folder = self.root / search_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "history.txt").write_text(text, encoding="utf-8")

    def latest(self, search_id: str) -> dict | None:
        paths = self._paths(search_id)
        if not paths:
            return None
        return _read(paths[-1])

    def get(self, search_id: str, stamp: str) -> dict | None:
        path = self.root / search_id / f"{stamp}.json"
        if not path.is_file():
            return None
        return _read(path)

    def all_runs(self, search_id: str) -> list[dict]:
        return [_read(path) for path in self._paths(search_id)]

    def stamps(self, search_id: str) -> list[str]:
        return [path.stem for path in self._paths(search_id)]

    def hidden(self, search_id: str) -> list[dict]:
        """Cars hidden from the page. They are still scraped and compared like any other."""
        path = self.root / search_id / "hidden.json"
        if not path.is_file():
            return []
        return list(_read(path).get("vehicles") or [])

    def hide(self, search_id: str, vehicle: dict, hidden_at: str) -> None:
        identity = car_identity(vehicle)
        with _HIDDEN_LOCK:
            entries = [entry for entry in self.hidden(search_id) if entry["identity"] != identity]
            entries.append(
                {
                    "identity": identity,
                    "plate": vehicle.get("plate") or "",
                    "title": vehicle.get("title") or "",
                    "price": vehicle.get("price"),
                    "url": vehicle.get("url") or "",
                    "hidden_at": hidden_at,
                }
            )
            self._write_hidden(search_id, entries)

    def unhide(self, search_id: str, identity: str) -> None:
        with _HIDDEN_LOCK:
            entries = [entry for entry in self.hidden(search_id) if entry["identity"] != identity]
            self._write_hidden(search_id, entries)

    def _write_hidden(self, search_id: str, entries: list[dict]) -> None:
        folder = self.root / search_id
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / "hidden.tmp"
        temp.write_text(json.dumps({"vehicles": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(folder / "hidden.json")

    def _paths(self, search_id: str) -> list[Path]:
        folder = self.root / search_id
        if not folder.is_dir():
            return []
        return sorted(path for path in folder.glob("????????T??????.json") if path.is_file())


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
