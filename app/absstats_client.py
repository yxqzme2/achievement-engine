# -----------------------------------------
# Section 1: Imports + Types
# -----------------------------------------

import requests
from typing import Any, Dict, List, Optional
from types import SimpleNamespace
from .models import UserSnapshot


# -----------------------------------------
# Section 2: ABSStatsClient Class + Constructor
# -----------------------------------------

class ABSStatsClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -----------------------------------------
    # Section 3: HTTP Helper
    # -----------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        r = requests.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # -----------------------------------------
    # Section 4: Core ABSStats Reads (Series / Items)
    # -----------------------------------------

    def get_series_index(self) -> List[Dict[str, Any]]:
        data = self._get("/api/series")
        series = data.get("series") or data
        return series if isinstance(series, list) else []

    def get_item(self, item_id: str) -> dict:
        return self._get(f"/api/item/{item_id}")

    def get_series(self, series_id: str) -> dict:
        return self._get(f"/api/series/{series_id}")

    # -----------------------------------------
    # Section 5: Users
    # -----------------------------------------

    def get_users(self):
        """
        Calls ABSStats:
          GET /api/users
        Returns lightweight objects with user_id, username, email.
        """
        data = self._get("/api/users")
        users = data.get("users") if isinstance(data, dict) else data
        if not isinstance(users, list):
            return []

        out = []
        for u in users:
            if not isinstance(u, dict):
                continue

            user_id = str(u.get("userId") or u.get("id") or "").strip()
            username = str(u.get("username") or u.get("name") or "").strip()
            email = u.get("email")

            if not user_id and username:
                user_id = username

            if not user_id:
                continue

            out.append(SimpleNamespace(user_id=user_id, username=username, email=email))

        return out

    # -----------------------------------------
    # Section 6: Completion Feeds
    # -----------------------------------------

    def get_completed(self, completed_endpoint: str) -> List[UserSnapshot]:
        data = self._get(completed_endpoint)
        users = data.get("users") or []
        if not isinstance(users, list):
            return []

        out: List[UserSnapshot] = []
        for u in users:
            user_id = str(u.get("userId") or u.get("id") or "").strip()
            username = str(u.get("username") or "").strip()
            if not user_id or not username:
                continue

            # 1. Parse finishedDates map (BookID -> Millisecond Timestamp)
            # We convert to Seconds for Python consistency.
            finished_dates_raw = u.get("finishedDates") or {}
            finished_dates: Dict[str, int] = {}

            if isinstance(finished_dates_raw, dict):
                for k, v in finished_dates_raw.items():
                    try:
                        ms = int(v)
                        finished_dates[str(k)] = int(ms / 1000)
                    except (ValueError, TypeError):
                        pass

            # 2. Build Set of Finished IDs
            # Use explicit finishedIds list if present, otherwise keys from dates
            raw_ids = u.get("finishedIds")
            if isinstance(raw_ids, list):
                finished_ids = set(map(str, raw_ids))
            else:
                finished_ids = set(finished_dates.keys())

            # Ensure synchronization
            finished_ids.update(finished_dates.keys())

            finished_count = int(u.get("finishedCount") or len(finished_ids))

            out.append(
                UserSnapshot(
                    user_id=user_id,
                    username=username,
                    email=u.get("email"),
                    finished_ids=finished_ids,
                    finished_dates=finished_dates,  # Populated with historical data
                    finished_count=finished_count,
                )
            )
        return out

    def get_playlist_fallback_finished(self) -> List[UserSnapshot]:
        data = self._get("/api/playlists")
        users = data.get("users") or []
        if not isinstance(users, list):
            return []

        out: List[UserSnapshot] = []
        for u in users:
            user_id = str(u.get("userId") or "").strip()
            username = str(u.get("username") or "").strip()
            if not username:
                continue

            finished_ids = set()
            # Note: Playlists endpoint doesn't support dates yet, so dict is empty
            playlists = u.get("playlists") or []
            for pl in playlists if isinstance(playlists, list) else []:
                items = pl.get("items") or []
                for it in items if isinstance(items, list) else []:
                    if it.get("finished") is True and it.get("libraryItemId"):
                        finished_ids.add(str(it["libraryItemId"]))

            out.append(
                UserSnapshot(
                    user_id=user_id or username,
                    username=username,
                    email=None,
                    finished_ids=finished_ids,
                    finished_dates={},
                    finished_count=len(finished_ids),
                )
            )
        return out

    # -----------------------------------------
    # Section 7: Listening Data Endpoints
    # -----------------------------------------

    def get_listening_sessions(self, since: str = None, limit: int = 50) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if since:
            params["since"] = since
        if limit:
            params["limit"] = str(limit)

        return self._get("/api/listening-sessions", params=params)

    def get_listening_time(self) -> Dict[str, Any]:
        return self._get("/api/listening-time")