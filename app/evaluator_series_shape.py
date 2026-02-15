from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from .models import Achievement

_NUM_RE = re.compile(r"(\d+)")


def _parse_first_int(s: str) -> Optional[int]:
    if not s: return None
    m = _NUM_RE.search(s.replace(",", ""))
    return int(m.group(1)) if m else None


def evaluate_series_shape(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        series_index: List[Dict],
        finished_ids: Set[str],
        client: Any,
) -> List[Tuple[Achievement, Dict]]:
    """
    Awards series-shape achievements.
    Backdates awards by finding the date the LAST book in the series was finished.
    """
    achs = [a for a in achievements if a.category == "series_shape"]
    if not achs: return []

    # Ensure we have strings
    done = set(str(x) for x in (finished_ids or set()))
    if not done: return []

    # Access the user's date map
    finished_dates = getattr(user, "finished_dates", {})

    series_by_id: Dict[str, Dict] = {}
    for s in series_index or []:
        sid = s.get("id") or s.get("seriesId")
        if sid: series_by_id[str(sid)] = s

    series_detail_cache: Dict[str, Optional[Dict]] = {}

    def get_series_info(sid: str) -> Dict:
        if sid not in series_detail_cache:
            try:
                raw = client.get_series(sid)
                data = raw.get("series") or raw.get("data") or raw if isinstance(raw, dict) else {}
                books = data.get("books") or data.get("items") or []
                if isinstance(books, list):
                    books.sort(
                        key=lambda b: float(b.get("sequence") or b.get("metadata", {}).get("seriesSequence") or 999))
                data["sorted_books"] = books
                series_detail_cache[sid] = data
            except:
                series_detail_cache[sid] = None
        return series_detail_cache[sid] or {}

    earned: List[Tuple[Achievement, Dict]] = []

    for ach in achs:
        trig = (ach.trigger or "").casefold()

        # 1. Duology / Trilogy / 10+ Books
        if any(key in trig for key in ["exactly 2", "trilogy", "10+ books", "more than 10"]):
            for sid in series_by_id.keys():
                info = get_series_info(sid)
                books = info.get("sorted_books", [])
                if not books: continue

                ids = [str(b.get("libraryItemId") or b.get("id")) for b in books]
                total = len(ids)
                complete = all(i in done for i in ids)

                if complete:
                    # Calculate series finish date (max of all books)
                    timestamps = [finished_dates.get(bid, 0) for bid in ids]
                    valid_ts = [t for t in timestamps if t > 0]
                    series_ts = max(valid_ts) if valid_ts else 0

                    if "exactly 2" in trig and total == 2:
                        earned.append((ach, {"series": info.get("name") or info.get("seriesName") or info.get("title") or "", "books": total, "_timestamp": series_ts}))
                        break
                    elif "trilogy" in trig and total == 3:
                        earned.append((ach, {"series": info.get("name") or info.get("seriesName") or info.get("title") or "", "books": total, "_timestamp": series_ts}))
                        break
                    elif ("10+" in trig or "more than 10" in trig) and total >= 10:
                        earned.append((ach, {"series": info.get("name") or info.get("seriesName") or info.get("title") or "", "books": total, "_timestamp": series_ts}))
                        break

        # 2. First book of N different series
        if "first book of" in trig:
            n = _parse_first_int(trig) or 5
            count = 0
            first_book_dates = []

            for sid in series_by_id.keys():
                info = get_series_info(sid)
                books = info.get("sorted_books", [])
                if not books: continue

                first_book_id = str(books[0].get("libraryItemId") or books[0].get("id"))
                if first_book_id in done:
                    count += 1
                    ts = finished_dates.get(first_book_id, 0)
                    if ts > 0:
                        first_book_dates.append(ts)

                if count >= n:
                    # Find date of the Nth series started
                    first_book_dates.sort()
                    milestone_ts = first_book_dates[n - 1] if len(first_book_dates) >= n else 0

                    earned.append((ach, {"threshold": n, "count": count, "_timestamp": milestone_ts}))
                    break

    return earned