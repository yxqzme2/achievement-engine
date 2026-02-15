from typing import List, Optional, Set, Dict, Any
from pydantic import BaseModel, Field, field_validator


def _coerce_to_list(v):
    """Accept a string, list, or None and always return a list of non-empty strings."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [s for s in v if isinstance(s, str) and s.strip()]


class Achievement(BaseModel):
    id: str
    category: str
    title: str
    trigger: Optional[str] = None
    points: int = 0
    iconPath: Optional[str] = None

    # Optional fields
    achievement: Optional[str] = None
    flavorText: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    # Fields for rarity and keywords
    rarity: str = "Common"
    keywords_any: List[str] = Field(default_factory=list)

    @field_validator("tags", "keywords_any", mode="before")
    @classmethod
    def coerce_list(cls, v):
        return _coerce_to_list(v)

    class Config:
        extra = "ignore"


class UserSnapshot(BaseModel):
    user_id: str
    username: Optional[str] = None

    # Existing set of IDs
    finished_ids: Set[str] = Field(default_factory=set)

    # NEW: Map of BookID -> Timestamp (epoch integer)
    finished_dates: Dict[str, int] = Field(default_factory=dict)

    finished_count: int = 0
    email: Optional[str] = None

    class Config:
        extra = "ignore"