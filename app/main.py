# -----------------------------------------
# Section 1
# -----------------------------------------
import time
import threading
import datetime
import os
from contextlib import asynccontextmanager
from typing import List, Tuple, Dict

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

# Your existing logic imports
from .config import load_settings
from .absstats_client import ABSStatsClient
from .achievements_loader import load_achievements, filter_phase1
from .evaluator_phase1 import evaluate_phase1
from .evaluator_behavior_time import evaluate_behavior_time
from .state_sqlite import StateStore
from .notifier_smtp import EmailNotifier
from .notifier_discord import DiscordNotifier
from .models import Achievement
from .evaluator_social import evaluate_social_overlap
from .evaluator_duration import evaluate_duration
from .evaluator_milestone_time import evaluate_milestone_time
from .evaluator_title_keyword import evaluate_title_keyword
from .evaluator_author import evaluate_author
from .evaluator_narrator import evaluate_narrator
from .evaluator_behavior_session import evaluate_behavior_session
from .evaluator_behavior_streak import evaluate_behavior_streak
from .evaluator_series_shape import evaluate_series_shape

# -----------------------------------------
# Section 2: Global Configuration & Initialization
# -----------------------------------------

cfg = load_settings()
store = StateStore(cfg.state_db_path)
client = ABSStatsClient(cfg.absstats_base_url)
notifier = EmailNotifier(
    host=cfg.smtp_host,
    port=cfg.smtp_port,
    username=cfg.smtp_username,
    password=cfg.smtp_password,
    from_addr=cfg.smtp_from
)
discord_notifier = DiscordNotifier(
    proxy_url=cfg.discord_proxy_url
)


# -----------------------------------------
# Section 3: Background Worker (The Engine)
# -----------------------------------------


def achievement_engine_worker():
    print("Background Achievement Engine Thread Started.")
    achievements = load_achievements(cfg.achievements_path)
    achievements_filtered = filter_phase1(achievements)
    series_index = []
    last_series_refresh = 0

    while True:
        now = int(time.time())
        if not series_index or (now - last_series_refresh) >= cfg.series_refresh_seconds:
            try:
                series_index = client.get_series_index()
                last_series_refresh = now
            except Exception as e:
                print(f"Series refresh failed: {e}")

        try:
            # We call run_once here
            run_once(
                client=client,
                store=store,
                notifier=notifier,
                achievements_filtered=achievements_filtered,
                series_index=series_index,
                completed_endpoint=cfg.completed_endpoint,
                allow_playlist_fallback=cfg.allow_playlist_fallback,
            )
        except Exception as e:
            print(f"Engine Loop Error: {e}")
        time.sleep(cfg.poll_seconds)


# -----------------------------------------
# Section 4: FastAPI App + Lifespan
# -----------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background thread on startup
    t = threading.Thread(target=achievement_engine_worker, daemon=True)
    t.start()
    yield
    # nothing on shutdown


app = FastAPI(lifespan=lifespan)

# -----------------------------------------
# Section 5: Web Routes + API (Dashboard data)
# -----------------------------------------

import json
from fastapi import HTTPException
from fastapi.responses import FileResponse

DASHBOARD_PATH = "/data/dashboard.html"
ACHIEVEMENTS_JSON_PATH = "/data/achievements.points.json"
ICONS_DIR = "/data/icons"

# Cache definitions so we don't re-read JSON on every request
_DEFS_CACHE = {"mtime": 0, "items": [], "by_id": {}}


def _load_defs_cached():
    try:
        st = os.stat(ACHIEVEMENTS_JSON_PATH)
        mtime = int(st.st_mtime)
    except FileNotFoundError:
        _DEFS_CACHE["mtime"] = 0
        _DEFS_CACHE["items"] = []
        _DEFS_CACHE["by_id"] = {}
        return _DEFS_CACHE

    if _DEFS_CACHE["items"] and _DEFS_CACHE["mtime"] == mtime:
        return _DEFS_CACHE

    with open(ACHIEVEMENTS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Your file is typically {"achievements":[...]}
    items = data["achievements"] if isinstance(data, dict) and "achievements" in data else data
    if not isinstance(items, list):
        items = []

    by_id = {}
    for a in items:
        ach_id = a.get("id") or a.get("achievement_id") or a.get("key")
        if ach_id:
            by_id[str(ach_id)] = a

    _DEFS_CACHE["mtime"] = mtime
    _DEFS_CACHE["items"] = items
    _DEFS_CACHE["by_id"] = by_id
    return _DEFS_CACHE


def _get_user_map_best_effort() -> Dict[str, str]:
    """
    Pull uuid -> username map from ABSStats /api/usernames.
    Do it via direct HTTP so we don't depend on ABSStatsClient implementing get_usernames().
    """
    user_map: Dict[str, str] = {}
    try:
        import urllib.request
        import json as _json

        url = cfg.absstats_base_url.rstrip("/") + "/api/usernames"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            u = _json.loads(raw)

        if isinstance(u, dict):
            if isinstance(u.get("map"), dict):
                user_map = {str(k): str(v) for k, v in u["map"].items()}
            elif isinstance(u.get("users"), list):
                for row in u["users"]:
                    uid = row.get("id")
                    un = row.get("username")
                    if uid and un:
                        user_map[str(uid)] = str(un)

        if not user_map:
            print(f"[api] /api/usernames returned empty map from {url}")

    except Exception as e:
        print(f"[api] /api/usernames fetch failed (continuing without usernames): {e}")

    return user_map


def _listening_seconds_by_user(listening_time_payload) -> Dict[str, int]:
    """
    listening_time_payload shapes vary over time; normalize safely.
    Expected common shapes:
      - {"users":[{"userId": "...", "listeningSeconds": 123, ...}, ...]}
      - {"users":[{"id": "...", "listeningSeconds": 123, ...}, ...]}
      - {"byUser":{"<uuid>": {"listeningSeconds": 123}}}
    """
    out: Dict[str, int] = {}
    if not listening_time_payload:
        return out

    if isinstance(listening_time_payload, dict):
        # byUser map form
        by_user = listening_time_payload.get("byUser")
        if isinstance(by_user, dict):
            for uid, row in by_user.items():
                try:
                    sec = int((row or {}).get("listeningSeconds", 0))
                except Exception:
                    sec = 0
                out[str(uid)] = sec
            return out

        # users list form
        users = listening_time_payload.get("users")
        if isinstance(users, list):
            for row in users:
                if not isinstance(row, dict):
                    continue
                uid = row.get("userId") or row.get("id") or row.get("user_id")
                if not uid:
                    continue
                try:
                    sec = int(row.get("listeningSeconds", 0))
                except Exception:
                    sec = 0
                out[str(uid)] = sec
            return out

    return out
def _count_books_by_year(snap) -> Dict[str, int]:
    fd = getattr(snap, "finished_dates", None) or {}
    from datetime import datetime
    counts: Dict[str, int] = {}
    for book_id, ts in fd.items():
        try:
            y = str(datetime.fromtimestamp(ts).year)
            counts[y] = counts.get(y, 0) + 1
        except Exception:
            pass
    return counts


def _next_milestone(current: int, milestones: List[int]):
    """
    Given current value and milestone thresholds, return a simple next-up object.
    """
    ms = sorted([m for m in milestones if isinstance(m, int) and m > 0])
    if not ms:
        return None

    for target in ms:
        if current < target:
            remaining = target - current
            pct = 0.0 if target <= 0 else min(1.0, max(0.0, current / target))
            return {
                "current": current,
                "target": target,
                "remaining": remaining,
                "percent": pct
            }

    # already beyond max milestone
    top = ms[-1]
    return {
        "current": current,
        "target": top,
        "remaining": 0,
        "percent": 1.0
    }


@app.get("/")
def read_dashboard():
    if not os.path.exists(DASHBOARD_PATH):
        raise HTTPException(status_code=404, detail=f"Missing {DASHBOARD_PATH}")
    return FileResponse(DASHBOARD_PATH)
LEADERBOARD_PATH = "/data/leaderboard.html"

@app.get("/leaderboard")
def read_leaderboard():
    if not os.path.exists(LEADERBOARD_PATH):
        raise HTTPException(status_code=404, detail=f"Missing {LEADERBOARD_PATH}")
    return FileResponse(LEADERBOARD_PATH)
TIMELINE_PATH = "/data/timeline.html"

@app.get("/timeline")
def read_timeline():
    if not os.path.exists(TIMELINE_PATH):
        raise HTTPException(status_code=404, detail=f"Missing {TIMELINE_PATH}")
    return FileResponse(TIMELINE_PATH)

@app.get("/achievements.points.json")
def achievements_points_json():
    if not os.path.exists(ACHIEVEMENTS_JSON_PATH):
        raise HTTPException(status_code=404, detail=f"Missing {ACHIEVEMENTS_JSON_PATH}")
    return FileResponse(ACHIEVEMENTS_JSON_PATH, media_type="application/json")


@app.get("/api/achievements")
def api_achievements():
    # legacy endpoint for older dashboard versions
    defs = _load_defs_cached()
    return JSONResponse(defs["items"])


@app.get("/api/definitions")
def api_definitions():
    # stable, explicit shape for the Awards Center
    defs = _load_defs_cached()
    return JSONResponse({
        "generated_at": int(time.time()),
        "total_definitions": len(defs["items"]),
        "achievements": defs["items"],
    })


@app.get("/icons/{icon_path:path}")
def get_icon(icon_path: str):
    safe = icon_path.replace("\\", "/").lstrip("/")
    full_path = os.path.join(ICONS_DIR, safe)

    # prevent path traversal
    norm_icons = os.path.abspath(ICONS_DIR)
    norm_full = os.path.abspath(full_path)
    if not norm_full.startswith(norm_icons + os.sep) and norm_full != norm_icons:
        raise HTTPException(status_code=400, detail="Invalid icon path")

    if not os.path.exists(norm_full):
        raise HTTPException(status_code=404, detail=f"Icon not found: {safe}")

    return FileResponse(norm_full)


@app.get("/api/awards")
def api_awards_all_users():
    """
    ALL USERS.
    Returns:
      - per-user awards (earned)
      - per-user point totals
      - leaderboard (sorted)
      - awards merged with definitions (title/icon/points/category/etc.)
      - user_map (uuid -> username) from ABSStats
    """
    defs = _load_defs_cached()
    by_id = defs["by_id"]

    user_map = _get_user_map_best_effort()

    awards = store.get_all_awards()
    users_map = {}

    for a in awards:
        user_id = a.get("user_id")
        achievement_id = str(a.get("achievement_id"))
        awarded_at = int(a.get("awarded_at") or 0)
        payload = a.get("payload") or {}

        d = by_id.get(achievement_id, {}) or {}

        pts = d.get("points", d.get("point", 0))
        try:
            pts = int(pts)
        except Exception:
            pts = 0

        merged = {
            "achievement_id": achievement_id,
            "awarded_at": awarded_at,
            "points": pts,
            "category": d.get("category"),
            "achievement": d.get("achievement") or d.get("title"),
            "title": d.get("title"),
            "flavorText": d.get("flavorText"),
            "iconPath": d.get("iconPath") or d.get("icon"),
            "payload": payload,
        }

        if user_id not in users_map:
            users_map[user_id] = {
                "user_id": user_id,
                "username": user_map.get(str(user_id), ""),
                "points": 0,
                "earned_count": 0,
                "awards": []
            }

        users_map[user_id]["awards"].append(merged)
        users_map[user_id]["points"] += pts
        users_map[user_id]["earned_count"] += 1

    for u in users_map.values():
        u["awards"].sort(key=lambda x: x.get("awarded_at", 0), reverse=True)

    users_list = list(users_map.values())
    users_list.sort(key=lambda x: (x["points"], x["earned_count"]), reverse=True)

    leaderboard = [
        {
            "user_id": u["user_id"],
            "username": u.get("username") or user_map.get(str(u["user_id"]), ""),
            "points": u["points"],
            "earned_count": u["earned_count"]
        }
        for u in users_list
    ]

    return JSONResponse({
        "generated_at": int(time.time()),
        "total_users": len(users_list),
        "total_definitions": len(defs["items"]),
        "user_map": user_map,
        "leaderboard": leaderboard,
        "users": users_list,
    })


@app.get("/api/progress")
def api_progress():
    """
    Progress data for the Awards Center (for "Next Up" + progress bars).

    Returns per-user:
      - metrics: finished_count, completed_series_count, listening_seconds, listening_hours
      - next_up: simple milestone progress objects (starter set)
      - user_map: uuid -> username
    """
    user_map = _get_user_map_best_effort()

    # Pull current stats (best-effort, don't crash the UI)
    try:
        snapshots = client.get_completed(cfg.completed_endpoint)
    except Exception as e:
        print(f"[api] /api/progress failed to fetch completions: {e}")
        snapshots = []

    try:
        listening_time_payload = client.get_listening_time()
    except Exception as e:
        print(f"[api] /api/progress failed to fetch listening time: {e}")
        listening_time_payload = None

    listen_sec = _listening_seconds_by_user(listening_time_payload)
    # Fetch series data for progress tracking
    try:
        import urllib.request, json as _json
        _sreq = urllib.request.Request(f"{cfg.absstats_base_url}/api/series")
        _sresp = urllib.request.urlopen(_sreq, timeout=10)
        all_series = _json.loads(_sresp.read()).get("series", [])
    except Exception as e:
        print(f"[api] /api/progress failed to fetch series: {e}")
        all_series = []

    # Starter milestone sets (we can swap these to match your evaluator IDs later)
    BOOK_MILESTONES = [5, 10, 20, 25, 50, 100]
    TIME_HOUR_MILESTONES = [1, 10, 50, 100, 500, 1000]

    users_out = []

    for snap in snapshots or []:
        raw_uid = getattr(snap, "user_id", None) or getattr(snap, "id", None) or getattr(snap, "userId", None)
        if not raw_uid:
            continue
        user_id = str(raw_uid)

        finished_ids = getattr(snap, "finished_ids", []) or []
        finished_count = len(finished_ids)

        # Count completed series by checking finished_ids against all_series
        completed_series_count = 0
        for sr in all_series:
            sr_books = sr.get("books", [])
            if len(sr_books) < 2:
                continue
            sr_book_ids = {b["libraryItemId"] for b in sr_books}
            if sr_book_ids.issubset(set(finished_ids)):
                completed_series_count += 1

        sec = int(listen_sec.get(str(user_id), 0) or 0)
        hours = sec / 3600.0

        # Series progress: find series >50% finished but not 100%
        series_progress = []
        for sr in all_series:
            sr_books = sr.get("books", [])
            if len(sr_books) < 2:
                continue
            sr_book_ids = {b["libraryItemId"] for b in sr_books}
            done = len(sr_book_ids & set(finished_ids))
            total = len(sr_books)
            if done > 0 and done < total:
                series_progress.append({
                    "seriesName": sr.get("seriesName", ""),
                    "done": done,
                    "total": total,
                    "percent": round(done / total, 3),
                })
        series_progress.sort(key=lambda x: x["percent"], reverse=True)

        users_out.append({
            "user_id": user_id,
            "username": user_map.get(str(user_id), ""),
                        "metrics": {
                "finished_count": finished_count,
                "completed_series_count": completed_series_count,
                "listening_seconds": sec,
                "listening_hours": hours,
                "books_by_year": _count_books_by_year(snap),
            },
            "next_up": {
                "books_total": _next_milestone(finished_count, BOOK_MILESTONES),
                "listening_hours": _next_milestone(int(hours), TIME_HOUR_MILESTONES),
            },
            "series_progress": series_progress,
        })

    # Sort by listening hours then finished count (just so it's stable)
    users_out.sort(
        key=lambda u: (u["metrics"].get("listening_hours", 0), u["metrics"].get("finished_count", 0)),
        reverse=True
    )

    return JSONResponse({
        "generated_at": int(time.time()),
        "total_users": len(users_out),
        "user_map": user_map,
        "users": users_out,
    })


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "state_db_path": cfg.state_db_path,
        "achievements_path": cfg.achievements_path,
    })


@app.get("/api/routes")
def list_routes():
    out = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        out.append({
            "path": getattr(r, "path", ""),
            "methods": sorted(list(methods)) if methods else [],
            "name": getattr(r, "name", ""),
        })
    return JSONResponse(out)


@app.get("/api/ui-config")
def api_ui_config():
    """Serve user aliases and icon mappings for the frontend dashboards."""
    aliases = {}
    for pair in (os.getenv("USER_ALIASES", "") or "").split(","):
        pair = pair.strip()
        if ":" in pair:
            key, val = pair.split(":", 1)
            aliases[key.strip()] = val.strip()

    icons = {}
    for pair in (os.getenv("USER_ICONS", "") or "").split(","):
        pair = pair.strip()
        if ":" in pair:
            key, val = pair.split(":", 1)
            icons[key.strip()] = val.strip()

    return JSONResponse({"aliases": aliases, "icons": icons})


# -----------------------------------------
# Section 6: Core Engine Logic (run_once)
# -----------------------------------------

def run_once(client, store, notifier, achievements_filtered, series_index, completed_endpoint, allow_playlist_fallback):
    snapshots = []
    sessions_payload = None
    listening_time_payload = None

    # quick lookup so we can convert ids -> Achievement objects for email
    achievements_by_id = {str(a.id): a for a in achievements_filtered if getattr(a, "id", None) is not None}

    try:
        snapshots = client.get_completed(completed_endpoint)
    except Exception as e:
        print(f"Failed to fetch completions from ABSStats: {e}")
        return

    if not snapshots:
        return

    all_users = snapshots

    try:
        sessions_payload = client.get_listening_sessions()
    except Exception as e:
        print(f"Failed to fetch listening sessions (duration/behavior awards may be skipped): {e}")
        sessions_payload = None

    try:
        listening_time_payload = client.get_listening_time()
    except Exception as e:
        print(f"Failed to fetch listening time (milestone_time awards may be skipped): {e}")
        listening_time_payload = None

    for snap in snapshots:
        user_id = snap.user_id
        user_new_awards = []

        user_new_awards.extend(evaluate_phase1(snap, achievements_filtered, series_index))
        user_new_awards.extend(evaluate_social_overlap(snap, achievements_filtered, all_users, absstats_base_url=cfg.absstats_base_url))
        user_new_awards.extend(evaluate_duration(snap, achievements_filtered, sessions_payload))

        # CHANGED: Use sessions_payload instead of listening_time_payload so we can calculate the date!
        user_new_awards.extend(evaluate_milestone_time(snap, achievements_filtered, sessions_payload))

        user_new_awards.extend(
            evaluate_title_keyword(
                user=snap,
                achievements=achievements_filtered,
                finished_ids=snap.finished_ids,
                client=client,
            )
        )

        user_new_awards.extend(
            evaluate_author(
                user=snap,
                achievements=achievements_filtered,
                finished_ids=snap.finished_ids,
                client=client,
                series_index=series_index,
            )
        )

        user_new_awards.extend(
            evaluate_narrator(
                user=snap,
                achievements=achievements_filtered,
                finished_ids=snap.finished_ids,
                client=client,
            )
        )

        user_new_awards.extend(evaluate_behavior_time(snap, achievements_filtered, sessions_payload))

        user_new_awards.extend(
            evaluate_behavior_session(
                user=snap,
                achievements=achievements_filtered,
                sessions_payload=sessions_payload,
            )
        )

        user_new_awards.extend(
            evaluate_behavior_streak(
                user=snap,
                achievements=achievements_filtered,
                sessions_payload=sessions_payload,
            )
        )
        user_new_awards.extend(
            evaluate_series_shape(
                user=snap,
                achievements=achievements_filtered,
                series_index=series_index,
                finished_ids=snap.finished_ids,
                client=client,
            )
        )
        # --- Yearly milestone: Century Club (100 books in a calendar year) ---
        yearly_achs = [a for a in achievements_filtered if a.category == "milestone_yearly"]
        for ya in yearly_achs:
            trig = (ya.trigger or "").lower()
            if "books" in trig and "year" in trig:
                import re
                from datetime import datetime
                target = int(re.search(r"(\d+)", trig).group(1)) if re.search(r"(\d+)", trig) else 0
                if target > 0 and hasattr(snap, "finished_dates") and snap.finished_dates:
                    year_counts = {}
                    year_last_ts = {}
                    for book_id, ts in snap.finished_dates.items():
                        y = datetime.fromtimestamp(ts).year
                        year_counts[y] = year_counts.get(y, 0) + 1
                        if ts > year_last_ts.get(y, 0):
                            year_last_ts[y] = ts
                    for y, count in year_counts.items():
                        if count >= target:
                            user_new_awards.append((ya, {
                                "books": count,
                                "target": target,
                                "year": y,
                                "_timestamp": year_last_ts[y]
                            }))
                            break

        # --- Meta: The Completionist (earn 50 achievements) ---
        meta_achs = [a for a in achievements_filtered if a.category == "meta"]
        for ma in meta_achs:
            if store.is_awarded(user_id, ma.id):
                continue
            trig = (ma.trigger or "").lower()
            if "earn" in trig and "achievement" in trig:
                import re
                target = int(re.search(r"(\d+)", trig).group(1)) if re.search(r"(\d+)", trig) else 0
                if target > 0:
                    existing_count = len([a for a in store.get_all_awards() if a["user_id"] == user_id])
                    if existing_count >= target:
                        user_new_awards.append((ma, {
                            "total_achievements": existing_count,
                            "target": target,
                            "_timestamp": int(__import__("time").time())
                        }))

        if not user_new_awards:
            continue
        # --- Normalize: SQLite needs string achievement IDs (not Achievement objects) ---
        normalized_awards = []
        for ach, p_dict in user_new_awards:
            if hasattr(ach, "id"):
                ach_id = getattr(ach, "id")
            elif hasattr(ach, "key"):
                ach_id = getattr(ach, "key")
            elif hasattr(ach, "achievement_id"):
                ach_id = getattr(ach, "achievement_id")
            else:
                ach_id = ach  # assume already a string

            ach_id = str(ach_id)
            normalized_awards.append((ach_id, p_dict))

        # --- Filter out already-awarded achievements ---
        final_to_award = [(ach_id, p_dict) for ach_id, p_dict in normalized_awards
                          if not store.is_awarded(user_id, ach_id)]

        if not final_to_award:
            continue

        inserted_ids = store.record_awards(user_id, final_to_award)
        if not inserted_ids:
            continue

        print(f"Awarded {len(inserted_ids)} new achievements to {user_id}")

        # --- Build award objects for notifications ---
        username = (getattr(snap, "username", "") or user_id).strip()
        awards_for_notify = []
        for ach_id, _payload in final_to_award:
            a = achievements_by_id.get(str(ach_id))
            if a is not None:
                awards_for_notify.append(a)

        # --- Discord notification ---
        if awards_for_notify:
            try:
                discord_payloads = [p for _, p in final_to_award]
                discord_notifier.send_awards(username=username, awards=awards_for_notify, payloads=discord_payloads)
            except Exception as e:
                print(f"Discord failed: {e}")

        # --- Email notification ---
        _user_email_map = {}
        for pair in (os.getenv("USER_EMAILS", "") or "").split(","):
            pair = pair.strip()
            if ":" in pair:
                uname, uemail = pair.split(":", 1)
                _user_email_map[uname.strip()] = uemail.strip()
        to_addr = _user_email_map.get(username, "") or cfg.smtp_to_override or getattr(snap, "email", "") or ""
        to_addr = to_addr.strip()
        if not to_addr:
            print(f"Email skipped: no email for user {username} ({user_id})")
            continue
        if not awards_for_notify:
            print(f"Email skipped: could not map awarded ids for user {username}")
            continue
        try:
            notifier.send_awards(to_addr=to_addr, username=username, awards=awards_for_notify)
        except Exception as e:
            print(f"Email failed: {e}")

            # --- Discord notification ---
            try:
                discord_payloads = [p for _, p in final_to_award]
                discord_notifier.send_awards(username=username, awards=awards_for_notify, payloads=discord_payloads)
            except Exception as e:
                print(f"Discord failed: {e}")