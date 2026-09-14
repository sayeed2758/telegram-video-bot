# Advance Tera Video Bot — Phase 38

Phase 36 adds **manual backup & recovery tooling** without changing the runtime bot flow.

## Backup

Stop or pause heavy traffic before taking a backup, then run:

```bash
python tools/backup_data.py
```

Backups are written to `backups/` as timestamped ZIP files. The tool snapshots every `*.sqlite3` database in `data/` using SQLite's backup API and writes SHA-256 checksums into `manifest.json`.

## Restore

**Stop the bot first.** Then run:

```bash
python tools/restore_data.py backups/tera-video-bot-backup-YYYYMMDDTHHMMSSZ.zip
```

The restore tool validates checksums and SQLite integrity before replacing the active databases. Existing databases are moved into a timestamped `backups/pre-restore-*` folder.

## Databases covered

The backup automatically includes whichever SQLite files currently exist under `data/`, including the bot's history, analytics, users, and rate-limit data.

## Render note

Render service files are not a guaranteed permanent backup location. Keep important backup ZIPs outside the running service (for example, download them to your computer or upload them to a trusted storage location). **Do not commit SQLite databases or API secrets to GitHub.**

## Phase 36 safety

No handler, resolver, queue, cache, webhook, or rate-limit runtime behavior was changed by this phase.

## Phase 37 — Admin User Management Polish

Phase 37 keeps the production resolver and user-facing processing flow unchanged while improving the admin side:

- `/users` — open the admin user-management list.
- `/finduser` — search by Telegram User ID, `@username`, or part of a user's name.
- Admin user details now show name, username, active/inactive status, last-seen time, usage, limits, and last successful processing time.
- Dashboard statistics now separate active and inactive registered users.
- Existing `/admin`, `/limit`, `/setlimit`, `/resetlimit`, `/broadcast`, `/analytics`, `/queue`, `/status`, and `/maintenance` remain available.

### Phase 37 file changes

**Replace:**
- `bot/users.py`
- `bot/admin_dashboard.py`
- `bot/handlers.py`
- `bot/system_control.py`
- `README.md`

**Untouched:** all resolver/cache/queue/history/profile/analytics/rate-limit data files and the `data/` directory.

No new Python dependencies were added.


## Phase 38 — Final UI/UX Polish

Phase 38 keeps the production processing stack unchanged and performs a final Telegram UI cleanup:

- Removes the confusing **Retry** action from the Home screen; Retry remains available on actual result/error screens.
- Adds **Session Status** to the Home quick actions.
- Adds quick **History** and **Profile** navigation to resolved-file and multi-file result screens.
- Keeps all existing callback routes and commands intact.
- Bumps the runtime version to **38.0.0**.

### Phase 38 file changes

**Replace:**
- `bot/keyboards.py`
- `bot/system_control.py`
- `README.md`

**Untouched:** resolver, cache, queue, history, profile, analytics, rate-limit, security, backup/recovery, users, admin dashboard, QA tools, and the `data/` directory.

No new Python dependencies were added.

## Phase 40 — Subscription Foundation (Manual Purchase Contact)

Phase 40 adds the subscription foundation without connecting a payment gateway.
Users can view premium plans and tap a purchase button that opens the owner's
Telegram chat with a pre-filled purchase request containing the selected plan,
Telegram User ID, and username.

### Plans

- **PRO** — 50 videos/day for 30 days.
- **UNLIMITED** — unlimited videos for 30 days.
- **FREE** remains the default plan with the existing daily quota.

The subscription database is `data/subscriptions.sqlite3`.
Active subscriptions take priority over the normal/admin daily limit. When the
stored `expires_at` time passes, the subscription is automatically treated as
expired and the user falls back to the normal rate-limit rules.

### New command

- `/subscription` — view the current plan/status and purchase options.

### Environment variables

Optional Render variables:

```text
SUBSCRIPTION_CONTACT_USERNAME=Dragonn_Exclusive
SUBSCRIPTION_DAYS=30
SUBSCRIPTIONS_DB_PATH=data/subscriptions.sqlite3
```

No payment gateway is connected in this phase. Subscription activation is
prepared for a future verified admin/payment flow; no payment screenshot or
user-provided claim can activate a plan automatically.

### Phase 40 file changes

**Replace:**
- `bot/config.py`
- `bot/handlers.py`
- `bot/keyboards.py`
- `bot/rate_limiter.py`
- `bot/profile.py`
- `bot/cleanup.py`
- `bot/system_control.py`
- `main.py`
- `README.md`

**Add:**
- `bot/subscription.py`

**Untouched:** resolver, cache, queue, history data, analytics, security,
backup/recovery tools, QA tools, and the existing `data/` directory contents.

No new Python dependencies were added.
