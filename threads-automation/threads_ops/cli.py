"""Command line entry point: `threads-ops <command>` (or `python -m threads_ops <command>`)."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

from .config import ROOT, env_presence, load_config
from .context import make_ctx

REQUIRED_ENV = ["APP_ENV", "THREADS_OPS_API_TOKEN", "LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "PUBLISH_MODE",
                "THREADS_OPS_DB"]


def _redact(msg: str) -> str:
    import os
    for k, v in os.environ.items():
        if v and len(v) >= 12 and any(s in k for s in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            msg = msg.replace(v, f"<{k}>")
    return msg


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record))


def _setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level, handlers=[h], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # httpx logs full URLs (Threads tokens are query params)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="threads-ops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("check-env", help="show which env vars are set (values are never printed)")
    a = sub.add_parser("init-account", help="register a live Threads account (no secrets are stored in the DB)")
    a.add_argument("--id", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--threads-user-id")
    a.add_argument("--token-env", default="THREADS_ACCESS_TOKEN", help="NAME of the env var holding the token")
    sub.add_parser("seed-demo")
    r = sub.add_parser("run", help="scheduler + worker daemon")
    r.add_argument("--no-scheduler", action="store_true")
    r.add_argument("--no-worker", action="store_true")
    r.add_argument("--tick-seconds", type=int, default=30)
    sub.add_parser("tick", help="run one scheduler tick and exit")
    w = sub.add_parser("work", help="process due jobs and exit")
    w.add_argument("--max", type=int, default=50)
    api = sub.add_parser("api")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8787)
    t = sub.add_parser("test-llm", help="one minimal generation call; nothing is saved as a post or published")
    t.add_argument("--account", default=None)
    sub.add_parser("export-openapi")
    b = sub.add_parser("backup")
    b.add_argument("dest")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    _setup_logging()
    cfg = load_config()

    if args.cmd == "check-env":
        pres = env_presence(REQUIRED_ENV + ["THREADS_ACCESS_TOKEN", "OPENAI_REASONING_EFFORT"])
        print(json.dumps({"app_env": cfg.app_env, "publish_mode": cfg.publish_mode, "llm_provider": cfg.llm_provider,
                          "openai_model": cfg.openai_model, "db_path": cfg.db_path, "env_set": pres}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export-openapi":
        ctx = make_ctx(cfg.__class__(**{**cfg.__dict__, "db_path": ":memory:"}))
        from .api import create_app
        spec = create_app(ctx).openapi()
        out = ROOT / "docs" / "openapi.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        return 0
    ctx = make_ctx(cfg)
    if args.cmd == "migrate":
        print("migrations up to date")
        return 0
    if args.cmd == "init-account":
        from .store import create_account
        acc = create_account(ctx.conn, args.id, args.name, data_scope="live", external_user_id=args.threads_user_id,
                             token_env=args.token_env, actor="cli")
        print(json.dumps({k: acc[k] for k in ("id", "display_name", "data_scope", "token_env")}, ensure_ascii=False))
        print("自動運用・本番投稿はOFFで作成しました。設定は管理画面から行ってください。")
        return 0
    if args.cmd == "seed-demo":
        from .demo import seed
        print(json.dumps(seed(ctx), ensure_ascii=False))
        return 0
    if args.cmd == "run":
        from .worker import Daemon
        logging.getLogger(__name__).info("daemon start env=%s publish_mode=%s llm=%s db=%s", cfg.app_env, cfg.publish_mode,
                                         cfg.llm_provider, cfg.db_path)
        Daemon(ctx, tick_seconds=args.tick_seconds).run(with_scheduler=not args.no_scheduler, with_worker=not args.no_worker)
        return 0
    if args.cmd == "tick":
        from .scheduler import tick
        print(json.dumps(tick(ctx), ensure_ascii=False))
        return 0
    if args.cmd == "work":
        from .worker import run_one
        n = 0
        while n < args.max and run_one(ctx, cfg.worker_id):
            n += 1
        print(json.dumps({"processed": n}))
        return 0
    if args.cmd == "api":
        import uvicorn

        from .api import create_app
        uvicorn.run(create_app(ctx), host=args.host, port=args.port, log_level="info", access_log=False)
        return 0
    if args.cmd == "test-llm":
        return _test_llm(ctx, args.account)
    if args.cmd == "backup":
        dest = Path(args.dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dest) as out:
            ctx.conn.backup(out)
        print(f"backup written to {dest}")
        return 0
    if args.cmd == "status":
        from .api_views import runtime
        from .store import list_accounts
        print(json.dumps({"runtime": runtime(ctx), "accounts": [a["id"] for a in list_accounts(ctx.conn, None)],
                          "llm": ctx.llm.availability()}, ensure_ascii=False, indent=2))
        return 0
    return 1


def _test_llm(ctx, account_id: str | None) -> int:
    """Minimal connectivity check: one short generation with a 64-token cap. Uses a throwaway in-memory budget
    record when no account is given. Nothing is posted."""
    from .llm import AIUnavailable
    from .settings import AccountSettingsModel
    from .store import create_account, get_settings, list_accounts
    av = ctx.llm.availability()
    print(json.dumps({"provider": av["provider"], "model": av["model"], "available": av["available"],
                      "reason": av["reason"]}, ensure_ascii=False))
    if not av["available"]:
        return 2
    if account_id:
        s, _ = get_settings(ctx.conn, account_id)
    else:
        account_id = "__llm_check__"
        if account_id not in {a["id"] for a in list_accounts(ctx.conn, None)}:
            create_account(ctx.conn, account_id, "LLM接続確認用（投稿しない）", data_scope="test", actor="cli")
        s = AccountSettingsModel()
    # a tiny, explicit budget for this single check so it can never run away
    s.budget.daily_usd = s.budget.daily_usd if s.budget.daily_usd is not None else 0.05
    s.budget.monthly_usd = s.budget.monthly_usd if s.budget.monthly_usd is not None else 0.05
    s.budget.price_input_per_mtok_usd = s.budget.price_input_per_mtok_usd or 5.0     # deliberately high placeholder
    s.budget.price_output_per_mtok_usd = s.budget.price_output_per_mtok_usd or 20.0  # deliberately high placeholder
    s.budget.max_output_tokens = 256
    try:
        res = ctx.llm.complete(account_id, s, "llm_check", "JSONだけを返してください。",
                               '{"ok": true} という形のJSONを返してください。', json_mode=True)
    except AIUnavailable as e:
        print(json.dumps({"ok": False, "code": e.code, "error": _redact(str(e))}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": True, "chars": len(res.text), "input_tokens": res.input_tokens,
                      "output_tokens": res.output_tokens}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
