from __future__ import annotations

import re
from datetime import datetime, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo
from typing import Any, Dict, Iterable, List, Tuple

from .models import Achievement

NY_TZ = ZoneInfo("America/New_York")


def _ms_to_date(ms: int) -> datetime.date:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=NY_TZ)
    return dt.date()


def _extract_int(s: str) -> int:
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else 0


def evaluate_behavior_streak(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        sessions_payload: Dict,
) -> List[Tuple[Achievement, Dict]]:
    streak_achs = [a for a in achievements if a.category == "behavior_streak"]
    if not streak_achs: return []

    users = sessions_payload.get("users", [])
    user_sessions = next((u for u in users if str(u.get("userId")) == user.user_id), None)
    if not user_sessions: return []

    sessions = user_sessions.get("sessions", [])
    if not sessions: return []

    # Map: Date -> Max Timestamp seen on that date (to backdate awards correctly)
    date_max_ts: Dict[datetime.date, int] = {}
    listened_days = set()
    month_days = defaultdict(set)
    month_seconds: Dict[tuple, Dict] = {}

    for s in sessions:
        start_ms = s.get("startedAt")
        end_ms = s.get("updatedAt") or s.get("endedAt") or start_ms
        if not start_ms: continue

        try:
            d_start = _ms_to_date(start_ms)
            d_end = _ms_to_date(end_ms)
        except Exception:
            continue

        end_ts = int(end_ms / 1000)

        # Add every calendar day covered
        curr = d_start
        while curr <= d_end:
            listened_days.add(curr)
            month_days[(curr.year, curr.month)].add(curr.day)

            # Record the latest timestamp for this date
            if end_ts > date_max_ts.get(curr, 0):
                date_max_ts[curr] = end_ts

            curr += timedelta(days=1)

        # Track monthly listening time (use timeListening, not wall clock)
        time_listening = s.get("timeListening") or 0
        if time_listening > 0:
            s_date = _ms_to_date(start_ms)
            month_key = (s_date.year, s_date.month)
            if month_key not in month_seconds:
                month_seconds[month_key] = {"total": 0.0, "ts": 0}
            month_seconds[month_key]["total"] += time_listening
            if end_ts > month_seconds[month_key]["ts"]:
                month_seconds[month_key]["ts"] = end_ts

    if not listened_days: return []

    sorted_days = sorted(listened_days)

    # Calculate streaks
    # We need to find the "best" streak, but also capture the timestamp of the Nth day
    max_streak = 0
    current_streak = 0

    # Store (length, end_date) tuples
    streaks = []

    for i, d in enumerate(sorted_days):
        if i == 0:
            current_streak = 1
        else:
            prev = sorted_days[i - 1]
            if (d - prev).days == 1:
                current_streak += 1
            else:
                streaks.append((current_streak, prev))
                current_streak = 1
    # Final streak
    streaks.append((current_streak, sorted_days[-1]))

    max_streak = max(s[0] for s in streaks) if streaks else 0

    # Calculate Month Frequency
    max_month_days = 0
    best_month_key = None
    best_month_ts = 0  # Approximate (end of month)

    for key, distinct_days in month_days.items():
        count = len(distinct_days)
        if count > max_month_days:
            max_month_days = count
            best_month_key = key
            # Find last day of activity in this month to use as timestamp
            y, m = key
            last_day_in_month = max(distinct_days)
            # Find the timestamp from date_max_ts
            # Construct date object
            try:
                ld = datetime.date(y, m, last_day_in_month)  # Pseudo-code fix
                # actually datetime.date constructor is (year, month, day)
                target_d = [d for d in sorted_days if d.year == y and d.month == m][-1]
                best_month_ts = date_max_ts.get(target_d, 0)
            except:
                pass

    earned: List[Tuple[Achievement, Dict]] = []

    for ach in streak_achs:
        trig = (ach.trigger or "").lower()
        target = _extract_int(trig)
        if target <= 0: continue

        if "consecutive" in trig or "streak" in trig:
            if max_streak >= target:
                best_s = max(streaks, key=lambda x: x[0])
                end_date = best_s[1]
                ts = date_max_ts.get(end_date, 0)

                earned.append((ach, {
                    "streak": max_streak,
                    "target": target,
                    "endDate": str(end_date),
                    "_timestamp": ts
                }))

        elif "hours" in trig and "month" in trig:
                target_hours = _extract_int(trig)
                if target_hours > 0:
                    for mk, mdata in month_seconds.items():
                        if mdata["total"] / 3600.0 >= target_hours:
                            y, m = mk
                            earned.append((ach, {
                                "hours": round(mdata["total"] / 3600.0, 1),
                                "target": target_hours,
                                "month": f"{y:04d}-{m:02d}",
                                "_timestamp": mdata["ts"]
                            }))
                            break


        elif "distinct days" in trig and "month" in trig:
                if max_month_days >= target and best_month_key:
                    y, m = best_month_key
                    earned.append((ach, {
                        "days": max_month_days,
                        "target": target,
                        "month": f"{y:04d}-{m:02d}",
                        "_timestamp": best_month_ts
                    }))

    return earned