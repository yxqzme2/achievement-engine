from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from .models import Achievement


def _to_list(v) -> List[str]:
    if v is None: return []
    if isinstance(v, list): return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    return []


def _get_searchable_text(item: Dict) -> str:
    """Combines title and subtitle for a comprehensive keyword search."""
    search_parts = []

    # Check main payload
    for key in ("title", "name", "subtitle"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            search_parts.append(val.strip())

    # Check media object (Standard Audiobookshelf shape)
    media = item.get("media")
    if isinstance(media, dict):
        meta = media.get("metadata") or {}
        for key in ("title", "name", "subtitle"):
            val = media.get(key) or meta.get(key)
            if isinstance(val, str) and val.strip():
                search_parts.append(val.strip())

    return " ".join(search_parts)


def evaluate_title_keyword(
        *,
        user: Any,
        achievements: Iterable[Achievement],
        finished_ids: Set[str],
        client: Any,
) -> List[Tuple[Achievement, Dict]]:
    kw_achs = [a for a in achievements if a.category == "title_keyword"]
    if not kw_achs: return []

    ids = [str(x) for x in (finished_ids or set())]
    if not ids: return []

    item_cache: Dict[str, Optional[Dict]] = {}

    def get_item(item_id: str) -> Optional[Dict]:
        if item_id not in item_cache:
            try:
                item_cache[item_id] = client.get_item(item_id)
            except Exception as e:
                print(f"[title_keyword] get_item FAILED item_id={item_id} err={e}")
                item_cache[item_id] = None
        return item_cache[item_id]

    earned: List[Tuple[Achievement, Dict]] = []
    ach_rules: List[Tuple[Achievement, List[str]]] = []

    for ach in kw_achs:
        keywords = _to_list(getattr(ach, "keywords_any", None))
        if not keywords:
            # Fallback to trigger parsing if keywords_any is missing
            trig = (ach.trigger or "").lower()
            if "with " in trig and " in the title" in trig:
                try:
                    content = trig.split("with ")[1].split(" in the title")[0]
                    keywords = [p.strip() for p in content.replace(" or ", ",").split(",") if p.strip()]
                except Exception:
                    pass

        if keywords:
            ach_rules.append((ach, keywords))

    # Access the user's date map
    finished_dates = getattr(user, "finished_dates", {})

    for item_id in ids:
        item = get_item(item_id) or {}
        full_text = _get_searchable_text(item)
        if not full_text: continue

        for ach, keywords in ach_rules:
            matched = None
            for kw in keywords:
                # Use regex with word boundaries (\b)
                pattern = r'\b' + re.escape(kw.lower()) + r'\b'
                if re.search(pattern, full_text.lower()):
                    matched = kw
                    break

            if matched:
                # Get the date this specific item was finished
                ts = finished_dates.get(item_id, 0)

                earned.append((
                    ach,
                    {
                        "itemId": item_id,
                        "title": full_text,
                        "matched": matched,
                        "_timestamp": ts
                    }
                ))

    return earned