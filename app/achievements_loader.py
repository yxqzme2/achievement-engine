import json
import os
from typing import List
from .models import Achievement


def load_achievements(json_path: str) -> List[Achievement]:
    """
    Loads achievements from a JSON file and converts them into Achievement objects.
    """
    if not os.path.exists(json_path):
        print(f"[loader] Achievements file not found at: {json_path}")
        return []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        # Support both raw list and {"achievements": [...]} formats
        if isinstance(raw, dict) and "achievements" in raw:
            data = raw["achievements"]
        elif isinstance(raw, list):
            data = raw
        else:
            print("[loader] JSON root is neither list nor dict with 'achievements' key.")
            return []

        loaded = []
        for entry in data:
            try:
                # Ensure 'id' field exists (map achievement_id if necessary)
                if "id" not in entry and "achievement_id" in entry:
                    entry["id"] = entry["achievement_id"]

                # Create model instance
                ach = Achievement(**entry)
                loaded.append(ach)
            except Exception as e:
                print(f"[loader] Failed to load achievement entry: {entry.get('title', 'Unknown')} - {e}")

        print(f"[loader] Loaded {len(loaded)} achievements from {json_path}")
        return loaded

    except Exception as e:
        print(f"[loader] Critical error loading achievements: {e}")
        return []


def filter_phase1(achievements: List[Achievement]) -> List[Achievement]:
    """
    Pass-through filter. 
    Can be used later to disable specific categories or 'coming soon' achievements.
    """
    return achievements