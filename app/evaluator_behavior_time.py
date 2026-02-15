from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple

from .models import Achievement, UserSnapshot

def _ms_to_local_dt(ms: int, tz_name: str) -> datetime:
    try:
        # ABS gives epoch milliseconds
        tz = ZoneInfo(tz_name)
    except Exception:
        # Fallback if timezone string is invalid
        tz = ZoneInfo("UTC")
    return datetime.fromtimestamp(ms / 1000.0, tz=tz)

def evaluate_behavior_time(
    user: UserSnapshot,
    achievements: List[Achievement],
    sessions_payload: Dict,
) -> List[Tuple[Achievement, Dict]]:
    """
    Evaluates time-based behavior achievements.
    Backdates by using the session timestamp.
    """
    earned: List[Tuple[Achievement, Dict]] = []

    # 1. Get sessions for this user
    users = sessions_payload.get("users") or []
    ublock = None
    for u in users:
        if str(u.get("userId")) == user.user_id:
            ublock = u
            break

    if not ublock:
        return earned

    sessions = ublock.get("sessions") or []
    if not sessions:
        return earned

    # 2. Iterate achievements
    for ach in achievements:
        if ach.category != "behavior_time":
            continue

        trigger_text = (ach.trigger or "").lower()

        # --- Logic for "2:00 AM" Achievement ---
        if "2:00 am" in trigger_text:
            target_tz = "America/New_York"
            target_days = {0, 1, 2, 3, 4}  # Mon-Fri
            start_hour = 2
            end_hour = 5

            for s in sessions:
                ts_ms = s.get("endedAt") or s.get("updatedAt")
                if not ts_ms:
                    continue

                try:
                    dt = _ms_to_local_dt(int(ts_ms), target_tz)
                except Exception:
                    continue

                if dt.weekday() not in target_days:
                    continue

                if start_hour <= dt.hour < end_hour:
                    earned.append((
                        ach,
                        {
                            "sessionId": s.get("id"),
                            "libraryItemId": s.get("libraryItemId"),
                            "local_time": dt.strftime("%A %H:%M"),
                            "timezone": target_tz,
                            "_timestamp": int(ts_ms / 1000)
                        }
                    ))
                    break

        # --- Logic for "before 6:00 AM" Achievement ---
        if "before 6:00 am" in trigger_text:
            target_tz = "America/New_York"
            for s in sessions:
                ts_ms = s.get("startedAt")
                if not ts_ms:
                    continue
                try:
                    dt = _ms_to_local_dt(int(ts_ms), target_tz)
                except Exception:
                    continue
                if dt.hour < 6:
                    earned.append((
                        ach,
                        {
                            "sessionId": s.get("id"),
                            "libraryItemId": s.get("libraryItemId"),
                            "local_time": dt.strftime("%A %H:%M"),
                            "timezone": target_tz,
                            "_timestamp": int(ts_ms / 1000)
                        }
                    ))
                    break

    return earned