from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .models import Achievement


def _norm_name(s: str) -> str:
    return " ".join((s or "").strip().split()).casefold()


def _to_list(v) -> List[str]:
    if v is None: return []
    if isinstance(v, list): return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str): return [v.strip()] if v.strip() else []
    return []


def _extract_int(s: str) -> int:
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else 0


def _extract_authors(item: Dict) -> List[str]:
    authors = _to_list(item.get("authors")) or _to_list(item.get("author"))
    if authors: return authors
    media = item.get("media") or {}
    if isinstance(media, dict):
        authors = _to_list(media.get("authors")) or _to_list(media.get("author"))
        if authors: return authors
    meta = item.get("metadata") or {}
    if isinstance(meta, dict):
        authors = _to_list(meta.get("authors")) or _to_list(meta.get("author"))
        if authors: return authors
    return []


def _extract_narrators(item: Dict) -> List[str]:
    narrators = _to_list(item.get("narrators")) or _to_list(item.get("narrator"))
    if narrators: return narrators
    media = item.get("media") or {}
    if isinstance(media, dict):
        narrators = _to_list(media.get("narrators")) or _to_list(media.get("narrator"))
        if narrators: return narrators
    meta = item.get("metadata") or {}
    if isinstance(meta, dict):
        narrators = _to_list(meta.get("narrators")) or _to_list(meta.get("narrator"))
        if narrators: return narrators
    return []


def evaluate_author(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        finished_ids: Set[str],
        client: Any,
        series_index: Optional[List[Dict]] = None,
) -> List[Tuple[Achievement, Dict]]:
    author_achs = [a for a in achievements if a.category == "author"]
    if not author_achs: return []

    ids = [str(x) for x in (finished_ids or set())]
    if not ids: return []

    # User dates map
    finished_dates = getattr(user, "finished_dates", {})

    item_cache: Dict[str, Optional[Dict]] = {}

    def get_item(item_id: str) -> Optional[Dict]:
        if item_id not in item_cache:
            try:
                item_cache[item_id] = client.get_item(item_id)
            except Exception as e:
                item_cache[item_id] = None
        return item_cache[item_id]

    # 1. Analyze Finished Books
    # Map: AuthorKey -> List of Timestamps
    author_dates: Dict[str, List[int]] = defaultdict(list)
    author_display: Dict[str, str] = {}

    any_self_narrated = False
    self_narrated_ts = 0
    self_narrated_example: Dict[str, Any] = {}

    for item_id in ids:
        item = get_item(item_id) or {}
        ts = finished_dates.get(item_id, 0)

        authors = _extract_authors(item)
        narrators = _extract_narrators(item)

        for a in authors:
            key = _norm_name(a)
            if not key: continue
            author_dates[key].append(ts)
            author_display.setdefault(key, a)

        # Check for Self-Narrated
        if authors and narrators:
            author_keys = {_norm_name(a) for a in authors if _norm_name(a)}
            narrator_keys = {_norm_name(n) for n in narrators if _norm_name(n)}
            if author_keys & narrator_keys:
                any_self_narrated = True
                self_narrated_ts = ts
                title = item.get("title") or item.get("name") or ""
                self_narrated_example = {
                    "itemId": item_id,
                    "title": title if isinstance(title, str) else "",
                    "authors": ", ".join(authors),
                    "narrators": ", ".join(narrators),
                    "_timestamp": ts
                }

    distinct_author_count = len(author_dates)

    # 2. Analyze Completed Series
    # Map: AuthorKey -> List of SeriesCompletionTimestamps
    completed_series_dates: Dict[str, List[int]] = defaultdict(list)
    completed_series_author_display: Dict[str, str] = {}

    if series_index:
        for s in series_index:
            books = s.get("books") or []
            if not isinstance(books, list) or not books: continue

            series_book_ids = []
            for b in books:
                if isinstance(b, dict):
                    lid = b.get("libraryItemId") or b.get("id")
                    if lid: series_book_ids.append(str(lid))

            if not series_book_ids: continue

            if all(bid in finished_ids for bid in series_book_ids):
                # Calculate series completion date
                s_timestamps = [finished_dates.get(bid, 0) for bid in series_book_ids]
                valid_ts = [t for t in s_timestamps if t > 0]
                series_ts = max(valid_ts) if valid_ts else 0

                rep_id = series_book_ids[0]
                rep_item = get_item(rep_id) or {}
                rep_authors = _extract_authors(rep_item)

                for a in rep_authors:
                    key = _norm_name(a)
                    if not key: continue
                    completed_series_dates[key].append(series_ts)
                    completed_series_author_display.setdefault(key, a)

    # 3. Evaluate
    earned: List[Tuple[Achievement, Dict]] = []

    for ach in author_achs:
        trig = (ach.trigger or "").lower()
        target = _extract_int(trig)

        # A) Self-Narrated
        if "narrated by the author" in trig:
            if any_self_narrated:
                earned.append((ach, self_narrated_example))
            continue

        # B) Distinct Authors (Diversity)
        if "different authors" in trig or "distinct authors" in trig:
            if target > 0 and distinct_author_count >= target:
                # Find date of Nth distinct author
                # We sort all authors by their *earliest* book date
                earliest_per_author = []
                for dates in author_dates.values():
                    valid = [t for t in dates if t > 0]
                    if valid: earliest_per_author.append(min(valid))

                earliest_per_author.sort()
                milestone_ts = 0
                if len(earliest_per_author) >= target:
                    milestone_ts = earliest_per_author[target - 1]

                earned.append((ach, {
                    "count": distinct_author_count,
                    "target": target,
                    "_timestamp": milestone_ts
                }))
            continue

        # C) Series by Same Author
        if "complete series by the same author" in trig:
            if target > 0:
                best_key = None
                best_count = 0
                best_ts = 0

                for k, dates in completed_series_dates.items():
                    count = len(dates)
                    if count >= target and count > best_count:
                        best_key = k
                        best_count = count
                        # Date of the Nth series
                        sorted_dates = sorted([t for t in dates if t > 0])
                        if len(sorted_dates) >= target:
                            best_ts = sorted_dates[target - 1]

                if best_key:
                    earned.append((ach, {
                        "author": completed_series_author_display.get(best_key, best_key),
                        "seriesCount": best_count,
                        "target": target,
                        "_timestamp": best_ts
                    }))
            continue

        # D) Books by Same Author
        if "books by the same author" in trig:
            if target > 0:
                best_key = None
                best_count = 0
                best_ts = 0

                for k, dates in author_dates.items():
                    count = len(dates)
                    if count >= target and count > best_count:
                        best_key = k
                        best_count = count
                        # Date of Nth book
                        sorted_dates = sorted([t for t in dates if t > 0])
                        if len(sorted_dates) >= target:
                            best_ts = sorted_dates[target - 1]

                if best_key:
                    earned.append((ach, {
                        "author": author_display.get(best_key, best_key),
                        "count": best_count,
                        "target": target,
                        "_timestamp": best_ts
                    }))
            continue

    return earned