# Achievement Engine

An achievement/trophy system for [Audiobookshelf](https://www.audiobookshelf.org/). Automatically awards achievements based on listening activity — books finished, series completed, listening streaks, social overlap, and more.

## Features

- **50+ achievements** across categories: milestones, series, social, duration, behavior, streaks, and more
- **Automatic evaluation** — polls your Audiobookshelf server on a configurable interval and awards achievements as they're earned
- **Backdated awards** — achievements are timestamped to when they were actually earned, not when the engine discovered them
- **Discord notifications** — posts rich embeds to a Discord channel when achievements are earned
- **Email notifications** — optional SMTP-based email alerts
- **Web dashboard** — built-in leaderboard and timeline views
- **REST API** — `/api/awards`, `/api/progress`, `/api/definitions` for building custom UIs

## Architecture

The repo contains two services that work together:

```
┌──────────────────┐      ┌───────────┐      ┌───────────────────┐
│  Audiobookshelf  │─────▶│ abs-stats │─────▶│ achievement-engine│
│   (your server)  │      │ (port 3000)│      │    (port 8000)    │
└──────────────────┘      └───────────┘      └───────────────────┘
```

- **abs-stats** (`abs-stats/`) — a Node.js service that connects to your Audiobookshelf API, aggregates listening data (completions, sessions, series, etc.), and exposes it as a simplified REST API. It also proxies Discord webhooks and achievement engine endpoints.
- **achievement-engine** (root) — a Python/FastAPI service that polls abs-stats, evaluates achievement conditions, stores awards in SQLite, and serves the web dashboard.

## Prerequisites

- Docker and Docker Compose
- A running [Audiobookshelf](https://www.audiobookshelf.org/) server
- An Audiobookshelf API token (Settings > Users > your user > API Token)
- You will need a token for every user

## Quick Start

### Option A: Interactive setup (recommended)

```bash
git clone https://github.com/yxqzme2/achievement-engine.git
cd achievement-engine
chmod +x setup.sh
./setup.sh
docker compose up -d
```

The setup script will prompt you for your Audiobookshelf URL, API tokens, and optional settings. It creates `.env` and `docker-compose.override.yml` with your values.

### Option B: Manual setup

```bash
# 1. Clone the repo
git clone https://github.com/yxqzme2/achievement-engine.git
cd achievement-engine

# 2. Configure the achievement engine
cp .env.example .env
# Edit .env — set ABSSTATS_BASE_URL=http://abs-stats:3000

# 3. Configure abs-stats in docker-compose.yml
# Set ABS_URL to your Audiobookshelf server URL
# Set ABS_TOKEN to your Audiobookshelf API token
# For multi-user support, set ABS_TOKENS (see below)

# 4. Start both services
docker compose up -d

# 5. Open the dashboard
# http://localhost:8000
```

## Multi-User Setup

By default, abs-stats uses a single `ABS_TOKEN` and can only see that user's data. For a multi-user setup where the engine tracks all users, set `ABS_TOKENS` in `docker-compose.yml`:

```yaml
environment:
  - ABS_TOKENS=alice:token_for_alice,bob:token_for_bob
```

Get each user's API token from Audiobookshelf (Settings > Users > user > API Token).

You can also set `ALLOWED_USERNAMES` to restrict which users are tracked:

```yaml
environment:
  - ALLOWED_USERNAMES=alice,bob
```

Omit it or set `ALLOWED_USERNAMES=*` to track all users.

## Configuration

### Achievement Engine (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ABSSTATS_BASE_URL` | `http://localhost:3010` | Base URL of the abs-stats service |
| `POLL_SECONDS` | `300` | How often (seconds) to check for new achievements |
| `STATE_DB_PATH` | `/data/state.db` | Path to the SQLite state database |
| `ACHIEVEMENTS_PATH` | `/data/achievements.points.json` | Path to the achievements definition JSON |
| `SERIES_REFRESH_SECONDS` | `86400` | How often to refresh the series index |
| `COMPLETED_ENDPOINT` | `/api/completed` | abs-stats endpoint for completed books |
| `ALLOW_PLAYLIST_FALLBACK` | `true` | Fall back to playlist-based completion detection |
| `DISCORD_PROXY_URL` | *(empty)* | Discord webhook proxy URL; leave empty to disable |
| `USER_ALIASES` | *(empty)* | Display names — `user1:Name,user2:Name` |
| `USER_ICONS` | *(empty)* | Avatar paths — `user1:/icons/avatar1.png,user2:/icons/avatar2.png` |
| `SMTP_HOST` | *(empty)* | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USERNAME` | *(empty)* | SMTP username |
| `SMTP_PASSWORD` | *(empty)* | SMTP password |
| `SMTP_FROM` | *(empty)* | Sender email address |
| `SMTP_TO_OVERRIDE` | *(empty)* | Override all notification emails to this address |
| `USER_EMAILS` | *(empty)* | Per-user email mapping — `user1:a@b.com,user2:c@d.com` |
| `SEND_TEST_EMAIL` | `false` | Send a test email on startup |

### abs-stats (`docker-compose.yml` environment)

| Variable | Default | Description |
|---|---|---|
| `ABS_URL` | `http://audiobookshelf:80` | Your Audiobookshelf server URL |
| `ABS_TOKEN` | *(required)* | Audiobookshelf API token (admin or single-user) |
| `ABS_TOKENS` | *(empty)* | Multi-user tokens — `user1:token1,user2:token2` |
| `ENGINE_URL` | `http://localhost:8000` | Achievement engine URL (for proxying) |
| `ALLOWED_USERNAMES` | *(all users)* | Comma-separated username allowlist, or `*` for all |
| `DISCORD_WEBHOOK_URL` | *(empty)* | Discord webhook URL for notification proxy |
| `PORT` | `3000` | Port to listen on |

## Customizing Achievements

Edit `data/achievements.points.json` to add, remove, or modify achievements. Each achievement has:

- `id` — unique identifier
- `achievement` / `title` — display name
- `category` — evaluation category (`milestone`, `series`, `social`, `duration`, `behavior_time`, etc.)
- `trigger` — natural-language trigger string the evaluator parses
- `points` — point value
- `rarity` — `common` / `uncommon` / `rare` / `epic` / `legendary`
- `flavorText` — descriptive text shown in notifications
- `iconPath` — path to the achievement icon (place PNGs in `icons/`)

The engine re-reads the file on each evaluation cycle, so changes take effect without a restart.

## Adding User Avatars

Place avatar images in the `icons/` directory and map them in your `.env`:

```env
USER_ICONS=alice:/icons/alice.png,bob:/icons/bob.png
USER_ALIASES=alice:Alice,bob:Bob
```

## API Endpoints

### Achievement Engine (port 8000)

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /leaderboard` | Leaderboard HTML |
| `GET /timeline` | Timeline HTML |
| `GET /api/awards` | All users' earned achievements with definitions |
| `GET /api/progress` | Per-user progress metrics and next milestones |
| `GET /api/definitions` | All achievement definitions |
| `GET /api/ui-config` | User aliases and icon mappings for dashboards |
| `GET /icons/{path}` | Achievement icon files |
| `GET /health` | Health check |

### abs-stats (port 3000)

| Endpoint | Description |
|---|---|
| `GET /api/users` | All users with listening stats |
| `GET /api/usernames` | User ID to username mapping |
| `GET /api/completed` | Completed books per user |
| `GET /api/series` | All series with books |
| `GET /api/item/:id` | Single library item details |
| `GET /api/listening-sessions` | Listening sessions per user |
| `GET /api/listening-time` | Total listening time per user |
| `GET /api/cover/:id` | Book cover image proxy |
| `GET /health` | Health check |

## Data Persistence

All state is stored in a SQLite database at `STATE_DB_PATH` (default `/data/state.db`). Mount the `./data` directory as a volume to persist across container restarts. Awarded achievements are stored permanently — the engine only ever adds new awards, never removes them.

## License

[MIT](LICENSE)
