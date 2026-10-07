import logging
import os
import sys
import threading

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from waitress import serve

from watcher.config import load_config
from watcher.runner import Runner
from watcher.web import create_app

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["once"]:
        Runner().run()
        return

    cfg = load_config()
    timezone = pytz.timezone(cfg["timezone"])
    try:
        trigger = CronTrigger.from_crontab(cfg["schedule"], timezone=timezone)
    except ValueError as exc:
        raise SystemExit(f"Schedule {cfg['schedule']!r} is not a 5-field cron expression ({exc})") from exc

    runner = Runner()
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(runner.run, trigger, id="scrape", max_instances=1, coalesce=True)
    scheduler.start()
    if cfg["run_on_startup"]:
        threading.Thread(target=runner.run, name="startup-scrape", daemon=True).start()

    app = create_app(runner, scheduler)
    port = int(os.environ.get("PORT", "8080"))
    job = scheduler.get_job("scrape")
    log.info("Watching on http://0.0.0.0:%s", port)
    log.info("Next scheduled scrape: %s", job.next_run_time if job else "not scheduled")
    try:
        serve(app, host="0.0.0.0", port=port, threads=8)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
