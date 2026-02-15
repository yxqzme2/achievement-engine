import json
import urllib.request
from typing import List, Optional

from .models import Achievement

RARITY_COLORS = {
    "common": 0x9d9d9d,
    "uncommon": 0x1eff00,
    "rare": 0x0070dd,
    "epic": 0xa335ee,
    "legendary": 0xff8000,
}

def _load_user_aliases() -> dict:
    """Load user aliases from USER_ALIASES env var. Format: 'user1:Name,user2:Name'"""
    import os
    raw = os.getenv("USER_ALIASES", "")
    aliases = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            key, val = pair.split(":", 1)
            aliases[key.strip()] = val.strip()
    return aliases


USER_ALIASES = _load_user_aliases()


class DiscordNotifier:
    def __init__(self, proxy_url: str):
        """proxy_url = abs-stats endpoint, e.g. http://abs-stats:3000/api/discord-notify"""
        self.proxy_url = (proxy_url or "").strip()

    def enabled(self) -> bool:
        return bool(self.proxy_url)

    def send_awards(self, username: str, awards: List[Achievement], payloads: Optional[List[dict]] = None) -> None:
        if not self.enabled() or not awards:
            return

        display_name = USER_ALIASES.get(username, username)

        for i, a in enumerate(awards):
            rarity = (getattr(a, "rarity", "") or "Common").lower()
            color = RARITY_COLORS.get(rarity, 0x9d9d9d)
            rarity_label = rarity.capitalize()

            title = getattr(a, "achievement", "") or getattr(a, "title", "") or "Achievement"
            flavor = getattr(a, "flavorText", "") or ""
            points = getattr(a, "points", 0) or 0

            # Build extra fields from payload
            extra_fields = []
            if payloads and i < len(payloads):
                p = payloads[i] or {}
                # Book title (from Shared Experience or other)
                if p.get("bookTitle"):
                    extra_fields.append({"name": "Book", "value": p["bookTitle"], "inline": True})
                # Timestamp -> date
                ts = p.get("_timestamp", 0)
                if ts:
                    from datetime import datetime
                    date_str = datetime.fromtimestamp(ts).strftime("%B %d, %Y")
                    extra_fields.append({"name": "Date", "value": date_str, "inline": True})

            embed = {
                "title": f"🏆 {title}",
                "description": f"*\"{flavor}\"*" if flavor else "",
                "color": color,
                "fields": [
                              {"name": "Earned by", "value": display_name, "inline": True},
                              {"name": "Points", "value": str(points), "inline": True},
                              {"name": "Rarity", "value": rarity_label, "inline": True},
                          ] + extra_fields,
                "footer": {"text": "The System"},
            }

            payload = {
                "username": "The System",
                "embeds": [embed],
            }

            try:
                import time
                data = json.dumps(payload).encode()
                req = urllib.request.Request(
                    self.proxy_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=10)
                time.sleep(1)  # Rate limit: 1 message per second
            except Exception as e:
                print(f"[discord] Failed to send notification: {e}")