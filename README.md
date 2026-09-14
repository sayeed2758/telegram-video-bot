# Advance Tera Video Bot

Current project: **Phase 26 — User Profile Dashboard**

## Deployment
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- Required environment variables: `BOT_TOKEN`, `RENDER_EXTERNAL_URL`
- `PORT` is supplied by Render automatically.

## Phase 26 — User Profile Dashboard
Added a private `/profile` dashboard and **👤 Profile** buttons.

The profile shows:
- Telegram name, username and user ID
- Total successfully processed videos (from persistent daily usage records)
- Saved history entries currently available (up to the existing 10-entry history)
- Today's usage
- Daily limit
- Remaining videos for today

Also added a **🚦 My Limit** shortcut from the profile.

The existing Phase 23.3 direct-processing resolver and Phase 25 history system are preserved. No resolver/API flow was changed in this phase.

## Existing data
- Rate-limit database: `data/rate_limits.sqlite3`
- History database: `data/history.sqlite3`
- Existing environment overrides remain supported.

## Phase 27 – Admin Dashboard
- `/admin` opens an admin-only dashboard.
- Dashboard statistics include known users, active users today, successful videos, history entries, and custom limits.
- Admin can list users, inspect a user, find a user by Telegram ID, and set common daily limits from buttons.
- Limit actions: Block (0), 2/day, 5/day, 10/day, Unlimited (-1), or reset to the default limit.
- Admin access is controlled by `ADMIN_USER_IDS`.


## Phase 28 — Admin Broadcast System
- Added persistent Telegram user registry in `data/users.sqlite3`.
- Admin-only `📢 Broadcast` dashboard flow with preview and confirmation.
- Admin command: `/broadcast` (optionally `/broadcast Your message here`).
- Text-only broadcasts up to Telegram's 4096-character message limit.
- Sends to active registered users with controlled pacing.
- Automatically marks blocked/deleted chats inactive after delivery errors.
- Broadcast never exposes bot secrets or resolver URLs.

## Phase 29 — Analytics

Adds an admin-only analytics center with today / 7-day / 30-day request statistics, success/failure rate, videos processed, active users, average processing time, daily breakdown, top users, resolver quality breakdown, and top error categories.

New command: `/analytics`

New optional environment variable:
`ANALYTICS_DB_PATH=data/analytics.sqlite3`

The analytics database is created automatically. Analytics failures are isolated so they never block video processing.
## Phase 30.1 — Multi-link message fix

The bot now detects and processes every unique TeraBox link contained in a single Telegram message. Each link uses the existing queue, rate-limit, history, analytics, and resolver flow.

## Phase 30 — Resolver Queue & Concurrency

The bot now protects the upstream TeraBox resolver with a bounded FIFO queue. By default, at most 2 resolver jobs run at the same time, each user can have only one active/queued job, and up to 20 additional jobs may wait.

Optional Render environment variables:

- `MAX_CONCURRENT_RESOLVES=2`
- `MAX_RESOLVE_QUEUE_SIZE=20`

Admin tools:
- `/queue`
- Admin Dashboard → `⏳ Queue`

Temporary queue state is kept in memory for the running Render instance; it is intentionally not written to SQLite. Existing history, analytics, rate limits, broadcast, and resolver settings are preserved.


## Phase 31 — Result Cache & Duplicate Protection

Phase 31 adds a short in-memory cache for successful resolved results and same-URL single-flight protection. Concurrent users sending the exact same TeraBox URL share one upstream resolver request instead of creating duplicate PlayTeraBox API calls.

Environment variables are optional:
- `RESULT_CACHE_TTL_SECONDS` — cache lifetime in seconds (default `120`)
- `RESULT_CACHE_MAX_ENTRIES` — maximum cached results (default `100`)

Resolved playback/download URLs are deliberately **not persisted to SQLite** because provider URLs can expire. The cache is cleared automatically when the Render process restarts.

A cache hit still counts normally against the requesting user's daily quota and appears in the user's history, because the bot is still delivering a processed video result to that user.


## Phase 33 — Security & Production Hardening

Optional Render variables:

```text
WEBHOOK_SECRET_TOKEN=<random secret token>
MAX_MESSAGE_LENGTH=12000
MAX_LINKS_PER_MESSAGE=10
```

`WEBHOOK_SECRET_TOKEN` is optional. When set, Telegram webhook requests must include the matching secret token. Leaving it empty preserves the current deployment behavior.

The bot now bounds incoming message size and the number of links processed from one message. Expected Telegram API errors are handled quietly, and webhook details are no longer printed as a full URL in application logs.
