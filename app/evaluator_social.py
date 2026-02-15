from typing import Dict, List, Tuple
from .models import Achievement, UserSnapshot


def evaluate_social_overlap(
        user: UserSnapshot,
        achievements: List[Achievement],
        all_users: List[UserSnapshot],
        min_overlap: int = 1,
        absstats_base_url: str = "",
) -> List[Tuple[Achievement, Dict]]:
    """
    Awards social overlap achievements.
    Backdates by finding the date YOU finished the book that created the overlap.
    """
    earned: List[Tuple[Achievement, Dict]] = []
    social_achs = [a for a in achievements if a.category == "social"]
    if not social_achs:
        return earned

    others = [u for u in all_users if u.user_id != user.user_id]
    if not others:
        return earned

    user_dates = getattr(user, "finished_dates", {})

    # --- Evaluate each social achievement ---
    for a in social_achs:
        trig = (a.trigger or "").lower()

        # --- A) "Shared Experience" — same book within same week ---
        if "same book" in trig and "same week" in trig:
            for other in others:
                other_dates = getattr(other, "finished_dates", {})
                intersection = user.finished_ids.intersection(other.finished_ids)
                for bid in intersection:
                    my_ts = user_dates.get(bid, 0)
                    their_ts = other_dates.get(bid, 0)
                    if my_ts > 0 and their_ts > 0:
                        diff_days = abs(my_ts - their_ts) / 86400.0
                        if diff_days <= 7:
                            # Resolve book title
                            book_title = ""
                            if absstats_base_url:
                                try:
                                    import urllib.request, json
                                    url = f"{absstats_base_url.rstrip('/')}/api/item/{bid}"
                                    item_data = json.loads(urllib.request.urlopen(url).read())
                                    book_title = item_data.get("title", "")
                                except Exception:
                                    pass
                            earned.append((a, {
                                "bookId": bid,
                                "bookTitle": book_title,
                                "otherUser": other.username or other.user_id,
                                "daysBetween": round(diff_days, 1),
                                "_timestamp": max(my_ts, their_ts)
                            }))
                            break
                if any(ea[0].id == a.id for ea in earned):
                    break
            continue

        # --- B) Original "overlap with every user" logic ---
        overlap_details = []
        overlap_dates = []
        all_overlap = True

        for other in others:
            intersection = user.finished_ids.intersection(other.finished_ids)
            overlap_count = len(intersection)
            overlap_details.append({
                "otherUser": other.username or other.user_id,
                "overlap": overlap_count,
            })
            if overlap_count < min_overlap:
                all_overlap = False
                continue  # Bug A fix: was "return earned"

            shared_dates = [user_dates.get(bid, 0) for bid in intersection]
            valid_dates = sorted([t for t in shared_dates if t > 0])
            if len(valid_dates) >= min_overlap:
                overlap_dates.append(valid_dates[min_overlap - 1])
            else:
                overlap_dates.append(0)

        if all_overlap:
            final_ts = max(overlap_dates) if overlap_dates else 0
            earned.append((
                a,
                {
                    "min_overlap": min_overlap,
                    "overlaps": overlap_details,
                    "_timestamp": final_ts
                }
            ))

    return earned