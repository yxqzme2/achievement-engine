from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Tuple

from .models import Achievement


def _extract_hours(s: str) -> int:
    m = re.search(r"(\d+)\s*hour", (s or "").lower())
    return int(m.group(1)) if m else 0


def evaluate_behavior_session(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        sessions_payload: Dict,
) -> List[Tuple[Achievement, Dict]]:
    session_achs = [a for a in achievements if a.category == "behavior_session"]
    if not session_achs: return []

    users = sessions_payload.get("users", [])
    user_sessions = next((u for u in users if str(u.get("userId")) == user.user_id), None)
    if not user_sessions: return []

    sessions = user_sessions.get("sessions", [])
    if not sessions: return []

    # 1. Single Session Max
    max_session_seconds = 0.0
    max_session_ts = 0

    # 2. Weekend Grouping
    # Key: "YYYY-MM-DD" of the Saturday -> {total_seconds, last_timestamp}
    weekend_map: Dict[str, Dict] = defaultdict(lambda: {"total": 0.0, "ts": 0})

    # 3. Book Single Day
    book_days = defaultdict(lambda: {"first": None, "last": None, "ts": 0})
    finished_ids = set(getattr(user, "finished_ids", []) or [])

    for s in sessions:
        start_ms = s.get("startedAt")
        end_ms = s.get("updatedAt") or s.get("endedAt") or start_ms
        if not start_ms or not end_ms or end_ms <= start_ms: continue

        time_listening = s.get("timeListening") or 0
        if time_listening <= 0: continue
        # Cap at the smallest reasonable bound:
        # - book duration (can't listen more than the book's length)
        # - wall-clock time (can't listen more seconds than session was open)
        caps = [time_listening]
        book_dur = s.get("duration") or 0
        if book_dur > 0:
            caps.append(book_dur)
        wall = (end_ms - start_ms) / 1000.0
        if wall > 0:
            caps.append(wall)
        duration = min(caps)
        # Hard cap: no single session can exceed 24 hours
        duration = min(duration, 86400)

        # Track max session
        if duration > max_session_seconds:
            max_session_seconds = duration
            max_session_ts = int(end_ms / 1000)

        # Track weekends
        start_dt = datetime.fromtimestamp(start_ms / 1000.0)
        wd = start_dt.weekday()
        if wd in (5, 6):  # Sat/Sun
            delta = 0 if wd == 5 else 1
            sat_date = (start_dt - timedelta(days=delta)).date()
            k = str(sat_date)
            weekend_map[k]["total"] += duration
            # Keep the latest timestamp for this weekend to date the award
            if int(end_ms / 1000) > weekend_map[k]["ts"]:
                weekend_map[k]["ts"] = int(end_ms / 1000)

                # Track book days
                item_id = s.get("libraryItemId")
                if item_id and item_id in finished_ids:
                    s_date = start_dt.date()
                    e_date = datetime.fromtimestamp(end_ms / 1000.0).date()
                    entry = book_days[item_id]
                    if entry["first"] is None or s_date < entry["first"]: entry["first"] = s_date
                    if entry["last"] is None or e_date > entry["last"]: entry["last"] = e_date
                    # Capture completion timestamp (approx)
                    if int(end_ms / 1000) > entry["ts"]: entry["ts"] = int(end_ms / 1000)
                    # Track book total duration (for Speed Reader)
                    book_dur_s = s.get("duration") or 0
                    if book_dur_s > (entry.get("book_duration") or 0):
                        entry["book_duration"] = book_dur_s

    # Calculate max weekend
    max_weekend_seconds = 0.0
    max_weekend_ts = 0
    for k, v in weekend_map.items():
        if v["total"] > max_weekend_seconds:
            max_weekend_seconds = v["total"]
            max_weekend_ts = v["ts"]

    earned: List[Tuple[Achievement, Dict]] = []

    for ach in session_achs:
        trig = (ach.trigger or "").lower()
        target_hours = _extract_hours(trig)

        # A) Single Session Binge
        if "single listening session" in trig:
            if target_hours > 0 and max_session_seconds >= (target_hours * 3600):
                earned.append((ach, {
                    "seconds": int(max_session_seconds),
                    "hours": round(max_session_seconds / 3600, 2),
                    "target": target_hours,
                    "_timestamp": max_session_ts
                }))
            continue

        # B) Single Weekend Marathon
        if "over a single weekend" in trig:
            if target_hours > 0 and max_weekend_seconds >= (target_hours * 3600):
                earned.append((ach, {
                    "seconds": int(max_weekend_seconds),
                    "hours": round(max_weekend_seconds / 3600, 2),
                    "target": target_hours,
                    "_timestamp": max_weekend_ts
                }))
            continue

        # C) Finish in one day
        if "finish a book in a single day" in trig:
            for item_id, data in book_days.items():
                if data["first"] and data["last"] and data["first"] == data["last"]:
                    earned.append((ach, {
                        "itemId": item_id,
                        "date": str(data["first"]),
                        "_timestamp": data["ts"]
                    }))
                    break
            continue
            # D) Speed Reader — finish a 20+ hour book in under 7 days
        if "20+ hours" in trig and "7 days" in trig:
            for item_id, data in book_days.items():
                book_dur = data.get("book_duration") or 0
                if book_dur < 72000:  # 20 hours in seconds
                    continue
                if data["first"] and data["last"]:
                    span_days = (data["last"] - data["first"]).days + 1
                    if span_days <= 7:
                        earned.append((ach, {
                            "itemId": item_id,
                            "book_hours": round(book_dur / 3600, 1),
                            "days_taken": span_days,
                            "_timestamp": data["ts"]
                        }))
                        break
            continue
    return earned