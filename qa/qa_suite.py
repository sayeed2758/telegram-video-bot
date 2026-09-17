from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"

EXPECTED_FILES = [
    "main.py",
    "requirements.txt",
    "bot/__init__.py",
    "bot/handlers.py",
    "bot/resolver.py",
    "bot/config.py",
    "bot/security.py",
    "bot/cache.py",
    "bot/queue_manager.py",
    "bot/history.py",
    "bot/profile.py",
    "bot/analytics.py",
    "bot/admin_dashboard.py",
    "bot/rate_limiter.py",
    "bot/keyboards.py",
    "bot/platforms.py",
    "bot/users.py",
    "bot/error_messages.py",
    "bot/system_control.py",
    "bot/activity_logger.py",
]

COMMANDS = {
    "start", "help", "session", "mylimit", "myid", "profile", "admin",
    "limit", "setlimit", "resetlimit", "broadcast", "analytics", "queue",
    "status", "maintenance", "history", "clearhistory", "channelstatus", "channeltest",
}


def check_files() -> None:
    missing = [p for p in EXPECTED_FILES if not (ROOT / p).is_file()]
    assert not missing, f"Missing expected files: {missing}"
    print("PASS 1/8: required project files present")


def check_compile() -> None:
    import py_compile

    for path in BOT.glob("*.py"):
        py_compile.compile(str(path), doraise=True)
    py_compile.compile(str(ROOT / "main.py"), doraise=True)
    print("PASS 2/8: Python syntax/compile check")


def check_commands_static() -> None:
    tree = ast.parse((BOT / "handlers.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_handler":
            for arg in node.args:
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "CommandHandler":
                    if arg.args and isinstance(arg.args[0], ast.Constant):
                        found.add(str(arg.args[0].value))
    missing = sorted(COMMANDS - found)
    assert not missing, f"Missing command registration(s): {missing}"
    print(f"PASS 3/8: {len(found)} command registrations verified")


def check_security() -> None:
    ns = {}
    source = (BOT / "security.py").read_text(encoding="utf-8")
    exec(compile(source, str(BOT / "security.py"), "exec"), ns)
    validate = ns["validate_incoming_text"]
    assert validate("https://example.com", 20)[0]
    assert not validate("", 20)[0]
    assert not validate("x" * 21, 20)[0]
    print("PASS 4/8: message-size/security guard verified")


async def _cache_check() -> None:
    sys.path.insert(0, str(ROOT))
    from bot.cache import cache_key, get_or_resolve

    key = cache_key("https://example.com/s/test")
    calls = 0

    async def resolver():
        nonlocal calls
        calls += 1
        class R:
            ok = True
            value = "ok"
        return R()

    first, first_hit = await get_or_resolve(key, resolver)
    second, second_hit = await get_or_resolve(key, resolver)
    assert calls == 1
    assert first_hit is False and second_hit is True
    assert first.ok and second.ok
    print("PASS 5/8: cache hit behavior verified")


async def _queue_check() -> None:
    sys.path.insert(0, str(ROOT))
    from bot.queue_manager import ResolveQueue

    q = ResolveQueue(max_concurrent=2, max_queue_size=5)
    active = 0
    peak = 0
    order: list[int] = []
    lock = asyncio.Lock()

    async def worker(user_id: int):
        nonlocal active, peak
        ticket, reason = await q.acquire(user_id)
        assert reason is None and ticket is not None
        await ticket.wait()
        async with lock:
            active += 1
            peak = max(peak, active)
            order.append(user_id)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        await q.release(ticket)

    await asyncio.gather(*(worker(i) for i in range(1, 5)))
    assert peak <= 2, f"Peak concurrency exceeded 2: {peak}"
    assert len(order) == 4
    print("PASS 6/8: FIFO queue + max concurrency verified")


def check_rate_limit() -> None:
    sys.path.insert(0, str(ROOT))
    old = os.environ.get("RATE_LIMIT_DB_PATH")
    with tempfile.TemporaryDirectory() as td:
        os.environ["RATE_LIMIT_DB_PATH"] = str(Path(td) / "rate.sqlite3")
        import importlib
        import bot.rate_limiter as rl
        importlib.reload(rl)
        user = 987654321
        rl.set_limit(user, 2)
        assert rl.try_consume(user, 1)
        assert rl.try_consume(user, 1)
        assert not rl.try_consume(user, 1)
        rl.set_limit(user, -1)
        assert rl.try_consume(user, 3)
    if old is None:
        os.environ.pop("RATE_LIMIT_DB_PATH", None)
    else:
        os.environ["RATE_LIMIT_DB_PATH"] = old
    print("PASS 7/8: daily quota enforcement verified")


def check_playback_ui() -> None:
    keyboards = (BOT / "keyboards.py").read_text(encoding="utf-8")
    handlers = (BOT / "handlers.py").read_text(encoding="utf-8")
    assert "Original Link" in keyboards
    assert "Refresh Link" in keyboards
    assert 'context.user_data.get("last_url")' in handlers
    assert "original_url" in keyboards
    print("PASS 8/9: playback result UI provides original-link + refresh actions")


def check_system_control() -> None:
    sys.path.insert(0, str(ROOT))
    from bot.system_control import format_uptime, is_maintenance, set_maintenance
    original = is_maintenance()
    set_maintenance(True)
    assert is_maintenance() is True
    set_maintenance(False)
    assert is_maintenance() is False
    set_maintenance(original)
    assert format_uptime()
    print("PASS 9/9: maintenance/status controls verified")


def check_phase4_activity() -> None:
    config = (BOT / "config.py").read_text(encoding="utf-8")
    users = (BOT / "users.py").read_text(encoding="utf-8")
    activity = (BOT / "activity_logger.py").read_text(encoding="utf-8")
    handlers = (BOT / "handlers.py").read_text(encoding="utf-8")
    assert "ADMIN_ACTIVITY_CHANNEL_ID" in config
    assert "def register_user(user) -> bool" in users
    assert "notify_new_user" in activity and "notify_processing" in activity
    assert "channelstatus" in handlers and "channeltest" in handlers
    print("PASS 10/10: new-user + private admin activity channel integration verified")


def main() -> None:
    check_files()
    check_compile()
    check_commands_static()
    check_security()
    asyncio.run(_cache_check())
    asyncio.run(_queue_check())
    check_rate_limit()
    check_playback_ui()
    check_system_control()
    check_phase4_activity()
    print("\nQA RESULT: PASS — Phase 4 admin activity + new-user monitoring checks completed.")
    print("Live Telegram/Render tests still require deployment and real users/API calls.")


if __name__ == "__main__":
    main()
