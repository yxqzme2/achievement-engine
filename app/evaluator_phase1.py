import re
from typing import Dict, List, Optional, Set, Tuple
from .models import Achievement, UserSnapshot


def _extract_int(s: str) -> int:
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else -1


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _series_name_from_achievement(a: Achievement) -> Optional[str]:
    t = (a.trigger or "").strip()
    m = re.match(r"(?i)(?:complete|finish)\s+all\s+books\s+in\s+(.+)$", t)
    if m: return m.group(1).strip()
    if a.title: return a.title.strip()
    return None


def _find_series_by_name(series_index: List[Dict], target_name: str) -> Optional[Dict]:
    target_norm = _norm(target_name)
    if not target_norm: return None
    for s in series_index:
        name = (s.get("name") or s.get("title") or s.get("seriesName") or s.get("series") or "")
        if _norm(str(name)) == target_norm: return s
    for s in series_index:
        name = (s.get("name") or s.get("title") or s.get("seriesName") or s.get("series") or "")
        if target_norm in _norm(str(name)): return s
    return None


def build_completed_series_set_with_dates(
        finished_ids: Set[str],
        finished_dates: Dict[str, int],
        series_index: List[Dict]
) -> Dict[str, int]:
    completed = {}
    for s in series_index:
        sid = str(s.get("seriesId") or s.get("id") or "").strip()
        if not sid: continue
        books = s.get("books") or []
        book_ids = [str(b.get("libraryItemId")) for b in books if isinstance(b, dict) and b.get("libraryItemId")]
        if not book_ids: continue

        if all(bid in finished_ids for bid in book_ids):
            timestamps = [finished_dates.get(bid, 0) for bid in book_ids]
            valid_ts = [t for t in timestamps if t > 0]
            series_finish_ts = max(valid_ts) if valid_ts else 0
            completed[sid] = series_finish_ts
    return completed


def evaluate_phase1(
        user: UserSnapshot,
        achievements: List[Achievement],
        series_index: List[Dict],
) -> List[Tuple[Achievement, Dict]]:
    earned: List[Tuple[Achievement, Dict]] = []

    completed_series_map = build_completed_series_set_with_dates(user.finished_ids, user.finished_dates, series_index)
    series_dates = sorted([ts for ts in completed_series_map.values() if ts > 0])
    completed_series_count = len(completed_series_map)
    book_dates = sorted([ts for ts in user.finished_dates.values() if ts > 0])

    for a in achievements:
        # 1. Total Books Milestones (Handles "Finish 1 book" naturally now)
        if a.category == "milestone_books":
            target = _extract_int(a.trigger)
            if target > 0 and user.finished_count >= target:
                milestone_ts = 0
                if len(book_dates) >= target:
                    milestone_ts = book_dates[target - 1]
                elif book_dates:
                    milestone_ts = book_dates[-1]

                earned.append((a, {
                    "finished_count": user.finished_count,
                    "target": target,
                    "_timestamp": milestone_ts
                }))

        # 2. Total Series Milestones
        elif a.category == "milestone_series":
            target = _extract_int(a.trigger)
            if target > 0 and completed_series_count >= target:
                milestone_ts = 0
                if len(series_dates) >= target:
                    milestone_ts = series_dates[target - 1]
                earned.append((a, {
                    "completed_series_count": completed_series_count,
                    "target": target,
                    "_timestamp": milestone_ts
                }))

        # 3. Specific Series Completion
        elif a.category == "series_complete":
            series_name = _series_name_from_achievement(a)
            if not series_name: continue
            series = _find_series_by_name(series_index, series_name)
            if not series: continue
            sid = str(series.get("seriesId") or series.get("id") or "")
            if sid in completed_series_map:
                series_ts = completed_series_map[sid]
                books = series.get("books") or []
                earned.append((a, {
                    "series_name": series_name,
                    "series_id": sid,
                    "books_total": len(books),
                    "_timestamp": series_ts
                }))

    return earned