import re
from typing import Dict, List, Tuple, Optional

from .models import Achievement, UserSnapshot


def _extract_hours(trigger: str) -> Optional[int]:
    t = (trigger or "").lower().replace(",", "")
    m = re.search(r"(\d+)\s*hour", t)
    return int(m.group(1)) if m else None

def evaluate_milestone_time(
        user: UserSnapshot,
        achievements: List[Achievement],
        sessions_payload: Dict,  # CHANGED: Now expects sessions, not just totals
) -> List[Tuple[Achievement, Dict]]:
    earned: List[Tuple[Achievement, Dict]] = []

    milestone_achs = [a for a in achievements if a.category == "milestone_time"]
    if not milestone_achs: return []

    # 1. Get user sessions
    users = sessions_payload.get("users") or []
    ublock = next((u for u in users if str(u.get("userId")) == user.user_id), None)
    if not ublock: return []  # Cannot calculate backdate without sessions

    sessions = ublock.get("sessions") or []
    if not sessions: return []

    # 2. Sort sessions chronologically by end time
    # (We want to find the moment the cumulative time crossed the line)
    def get_end_ts(s):
        return s.get("updatedAt") or s.get("endedAt") or s.get("startedAt") or 0

    valid_sessions = []
    for s in sessions:
        end = get_end_ts(s)
        if not end:
            continue
        dur = s.get("timeListening") or 0
        if dur > 0:
            valid_sessions.append((end, dur))

    valid_sessions.sort(key=lambda x: x[0])  # Sort by timestamp

    # 3. Calculate running total
    running_seconds = 0.0
    # Map: HourThreshold -> Timestamp when it was crossed
    milestone_dates: Dict[int, int] = {}

    # Pre-calculate thresholds we care about to avoid checking every second
    targets = set()
    for a in milestone_achs:
        h = _extract_hours(a.trigger)
        if h: targets.add(h)

    sorted_targets = sorted(list(targets))

    for ts, dur in valid_sessions:
        running_seconds += dur
        current_hours = running_seconds / 3600.0

        # Check if we just crossed a target
        for t in sorted_targets:
            if t not in milestone_dates and current_hours >= t:
                milestone_dates[t] = int(ts / 1000)

    # 4. Award
    total_hours = running_seconds / 3600.0

    for a in milestone_achs:
        hours = _extract_hours(a.trigger)
        if hours and total_hours >= hours:
            # Use the historical date if found, otherwise (fallback) now
            ts = milestone_dates.get(hours, 0)

            earned.append((
                a,
                {
                    "listeningHours": round(total_hours, 2),
                    "thresholdHours": hours,
                    "_timestamp": ts
                }
            ))

    return earned