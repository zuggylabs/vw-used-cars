import json
import secrets
import threading
from datetime import datetime
from pathlib import Path

FILE = "car_options.json"
FITTED = "fitted"
NOT_FITTED = "not_fitted"
_LOCK = threading.RLock()


class OptionsStore:
    """The options worth looking for, and what has been seen on each car, keyed by plate (or listing id)."""

    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / FILE

    def load(self) -> dict:
        with _LOCK:
            if not self.path.is_file():
                return {"options": [], "cars": {}}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{self.path} could not be read ({exc})") from exc
            data.setdefault("options", [])
            data.setdefault("cars", {})
            return data

    def options(self) -> list[dict]:
        return self.load()["options"]

    def save_list(self, names: dict[str, str], new_names: list[str]) -> None:
        """Rename options by id. A blank name removes the option and what was recorded for it."""
        with _LOCK:
            data = self.load()
            kept = []
            for option in data["options"]:
                name = " ".join((names.get(option["id"], option["name"]) or "").split())
                if name:
                    kept.append({"id": option["id"], "name": name[:80]})
            known = {option["name"].lower() for option in kept}
            for name in new_names:
                name = " ".join((name or "").split())[:80]
                if name and name.lower() not in known:
                    kept.append({"id": secrets.token_hex(4), "name": name})
                    known.add(name.lower())
            ids = {option["id"] for option in kept}
            for car in data["cars"].values():
                car[FITTED] = [option_id for option_id in car.get(FITTED, []) if option_id in ids]
                car[NOT_FITTED] = [option_id for option_id in car.get(NOT_FITTED, []) if option_id in ids]
            data["options"] = kept
            self._write(data)

    def car(self, identity: str) -> dict:
        car = self.load()["cars"].get(identity) or {}
        return {FITTED: car.get(FITTED, []), NOT_FITTED: car.get(NOT_FITTED, []), "updated_at": car.get("updated_at")}

    def set_car(self, identity: str, states: dict[str, str]) -> None:
        with _LOCK:
            data = self.load()
            ids = {option["id"] for option in data["options"]}
            fitted = [option_id for option_id, state in states.items() if option_id in ids and state == FITTED]
            not_fitted = [option_id for option_id, state in states.items() if option_id in ids and state == NOT_FITTED]
            if fitted or not_fitted:
                data["cars"][identity] = {
                    FITTED: fitted,
                    NOT_FITTED: not_fitted,
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            else:
                data["cars"].pop(identity, None)
            self._write(data)

    def summaries(self) -> dict[str, dict]:
        """Per car: fitted option names, how many are still unchecked, and a one-line description."""
        data = self.load()
        names = {option["id"]: option["name"] for option in data["options"]}
        found = {}
        for identity, car in data["cars"].items():
            fitted = [names[option_id] for option_id in names if option_id in car.get(FITTED, [])]
            checked = {option_id for option_id in car.get(FITTED, []) + car.get(NOT_FITTED, []) if option_id in names}
            if not checked:
                continue
            found[identity] = {
                "fitted": fitted,
                "unchecked": len(names) - len(checked),
                "text": ", ".join(fitted) or "None of the listed options",
            }
        return found

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
