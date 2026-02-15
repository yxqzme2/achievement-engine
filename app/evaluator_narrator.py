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
    return int(m.group(1)) if m else -1


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


def evaluate_narrator(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        finished_ids: Set[str],
        client: Any,
) -> List[Tuple[Achievement, Dict]]:
    narrator_achs = [a for a in achievements if a.category == "narrator"]
    if not narrator_achs: return []

    ids = [str(x) for x in (finished_ids or set())]
    if not ids: return []

    finished_dates = getattr(user, "finished_dates", {})

    item_cache: Dict[str, Optional[Dict]] = {}

    def get_item(item_id: str) -> Optional[Dict]:
        if item_id not in item_cache:
            try:
                item_cache[item_id] = client.get_item(item_id)
            except Exception as e:
                item_cache[item_id] = None
        return item_cache[item_id]

    # Map: NarratorKey -> List of Timestamps
    narrator_dates: Dict[str, List[int]] = defaultdict(list)
    narrator_display: Dict[str, str] = {}

    for item_id in ids:
        item = get_item(item_id) or {}
        ts = finished_dates.get(item_id, 0)

        narrators = _extract_narrators(item)
        for n in narrators:
            key = _norm_name(n)
            if not key: continue
            narrator_dates[key].append(ts)
            narrator_display.setdefault(key, n)

    earned: List[Tuple[Achievement, Dict]] = []

    for ach in narrator_achs:
        threshold = _extract_int(ach.trigger)
        if threshold <= 0: continue

        best_key = None
        best_count = 0
        best_ts = 0

        for k, dates in narrator_dates.items():
            count = len(dates)
            if count >= threshold and count > best_count:
                best_key = k
                best_count = count
                # Date of Nth book
                sorted_dates = sorted([t for t in dates if t > 0])
                if len(sorted_dates) >= threshold:
                    best_ts = sorted_dates[threshold - 1]

        if best_key:
            earned.append((ach, {
                "narrator": narrator_display.get(best_key, best_key),
                "count": int(best_count),
                "threshold": int(threshold),
                "_timestamp": best_ts
            }))

    return earned