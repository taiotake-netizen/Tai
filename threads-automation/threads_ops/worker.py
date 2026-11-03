"""Job worker and the combined daemon loop (scheduler + worker). Runs independently of any browser."""

from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

from . import analyzer, assistant, generator, jobs, publishing, reports, scheduler
from .context import Ctx
from .db import tx
from .llm import AIUnavailable
from .store import set_state
from .threads_api import ThreadsError
from .timeutil import now, now_iso, parse

log = logging.getLogger("threads_ops.worker")

HANDLERS = {
    "generate_post": generator.generate_post,
    "publish_post": publishing.publish_post,
    "collect_metrics": publishing.collect_metrics,
    "reconcile_post": publishing.reconcile_post,
    "analyze": analyzer.analyze,
    "daily_report": reports.run_report_job,
    "weekly_report": reports.run_report_job,
    "refill_ideas": generator.refill_ideas,
    "assistant": assistant.run,
    "check_connection": lambda ctx, job: publishing.check_connection(ctx, job["account_id"]),
}


def _retry_delay(job: dict, exc: Exception) -> timedelta | None:
    kind = job["kind"]
    if kind == "publish_post":
        return None                        # never auto-retry a write to Threads
    if isinstance(exc, AIUnavailable) and exc.code != "provider_error":
        return None                        # budget/config problems need a human
    if kind == "collect_metrics":
        return timedelta(minutes=30 * job["attempts"])
    if kind == "generate_post" and job.get("post_id"):
        return timedelta(minutes=10)
    return timedelta(minutes=15 * job["attempts"])


def run_one(ctx: Ctx, worker_id: str) -> dict | None:
    job = jobs.claim(ctx.conn, worker_id, max_ai_concurrency=ctx.cfg.ai_max_concurrency)
    if job is None:
        return None
    handler = HANDLERS.get(job["kind"])
    try:
        if handler is None:
            raise RuntimeError(f"unknown job kind {job['kind']}")
        result = handler(ctx, job)
        jobs.finish(ctx.conn, job, "succeeded", result=result if isinstance(result, dict) else None)
    except generator.Cancelled:
        jobs.finish(ctx.conn, job, "cancelled")
    except (AIUnavailable, ThreadsError) as e:
        delay = _retry_delay(job, e)
        if job["kind"] == "generate_post" and delay and job.get("post_id"):
            from .db import row
            p = row(ctx.conn.execute("SELECT slot_at FROM posts WHERE id=?", (job["post_id"],)).fetchone())
            if p and parse(p["slot_at"]) <= now() + delay:
                delay = None
        jobs.finish(ctx.conn, job, "failed", error=str(e), retry_in=delay)
    except Exception as e:  # noqa: BLE001 - one bad job must not stop the daemon
        log.exception("job %s failed", job["id"])
        jobs.finish(ctx.conn, job, "failed", error=f"{type(e).__name__}: {e}"[:500], retry_in=_retry_delay(job, e))
    return job


class Daemon:
    def __init__(self, ctx: Ctx, *, tick_seconds: int = 30, idle_sleep: float = 2.0):
        self.ctx = ctx
        self.tick_seconds = tick_seconds
        self.idle_sleep = idle_sleep
        self.stop = False

    def _signal(self, *_):
        log.info("shutdown requested; finishing current job")
        self.stop = True

    def run(self, *, with_scheduler: bool = True, with_worker: bool = True, max_loops: int | None = None) -> None:
        signal.signal(signal.SIGTERM, self._signal)
        signal.signal(signal.SIGINT, self._signal)
        last_tick = 0.0
        loops = 0
        wid = self.ctx.cfg.worker_id
        while not self.stop:
            loops += 1
            if with_scheduler and time.monotonic() - last_tick >= self.tick_seconds:
                try:
                    scheduler.tick(self.ctx)
                except Exception:  # noqa: BLE001
                    log.exception("scheduler tick failed")
                last_tick = time.monotonic()
            did = None
            if with_worker:
                did = run_one(self.ctx, wid)
                with tx(self.ctx.conn):
                    set_state(self.ctx.conn, f"worker:{wid}", {"last_seen": now_iso(),
                                                               "last_job": did["id"] if did else None})
            if max_loops is not None and loops >= max_loops:
                break
            if did is None:
                time.sleep(self.idle_sleep)
