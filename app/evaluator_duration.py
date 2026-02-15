import re
from typing import Dict, List, Tuple, Optional
from .models import Achievement, UserSnapshot


def _extract_count(s: str) -> int:
    m = re.search(r"(\d+)\s+book", (s or "").lower())
    return int(m.group(1)) if m else 1


def _parse_duration_rule(trigger: str) -> Optional[Tuple[str, float]]:
    t = (trigger or "").lower().strip()
    t = t.replace("longer than", "over").replace("shorter than", "under")
    m = re.search(r"(>=|<=)\s*(\d+(?:\.\d+)?)\s*hour", t)
    if m:
        op = m.group(1)
        hours = float(m.group(2))
        return ("over" if op == ">=" else "under", hours)
    m = re.search(r"\b(over|under)\b\s*(\d+(?:\.\d+)?)\s*hour", t)
    if m:
        mode = m.group(1)
        hours = float(m.group(2))
        return (mode, hours)
    return None


def evaluate_duration(
        user: UserSnapshot,
        achievements: List[Achievement],
        sessions_payload: Dict,
) -> List[Tuple[Achievement, Dict]]:
    earned: List[Tuple[Achievement, Dict]] = []
    dur_achs = [a for a in achievements if a.category in ("duration", "duration_based")]
    if not dur_achs: return earned

    users = sessions_payload.get("users") or []
    ublock = next((u for u in users if str(u.get("userId")) == user.user_id), None)
    if not ublock: return earned

    sessions = ublock.get("sessions") or []
    if not sessions: return earned

    # Build Map: ID -> Duration
    item_duration_sec: Dict[str, float] = {}
    for s in sessions:
        li = s.get("libraryItemId")
        dur = s.get("duration")
        if not li or dur is None: continue
        try:
            li = str(li)
            dur_f = float(dur)
        except:
            continue
        if li not in item_duration_sec or dur_f > item_duration_sec[li]:
            item_duration_sec[li] = dur_f

    if not item_duration_sec: return earned

    # Access finished dates
    finished_dates = getattr(user, "finished_dates", {})

    # Filter to finished items only, keep (id, duration, timestamp)
    finished_items = []
    for li, sec in item_duration_sec.items():
        if li in user.finished_ids:
            ts = finished_dates.get(li, 0)
            finished_items.append((li, sec, ts))

    if not finished_items: return earned

    for a in dur_achs:
        rule = _parse_duration_rule(a.trigger)
        if not rule: continue
        mode, hours = rule
        threshold_sec = hours * 3600.0
        required_count = _extract_count(a.trigger)

        matches = []
        if mode == "over":
            matches = [i for i in finished_items if i[1] >= threshold_sec]
        else:
            matches = [i for i in finished_items if i[1] <= threshold_sec]

        if len(matches) >= required_count:
            # Sort by date to find the Nth qualifying book
            matches.sort(key=lambda x: x[2])  # Sort by timestamp

            # The Nth book triggered the achievement
            trigger_item = matches[required_count - 1]
            trigger_ts = trigger_item[2]

            # For display, we might want the "best" example (longest/shortest),
            # but for timestamp we MUST use the Nth one.
            if mode == "over":
                best_match = max(matches, key=lambda x: x[1])
            else:
                best_match = min(matches, key=lambda x: x[1])

            earned.append((
                a,
                {
                    "matchedItemId": best_match[0],
                    "matchCount": len(matches),
                    "requiredCount": required_count,
                    "durationSeconds": best_match[1],
                    "durationHours": round(best_match[1] / 3600.0, 2),
                    "thresholdHours": hours,
                    "mode": mode,
                    "_timestamp": trigger_ts
                }
            ))

    return earned