from typing import List, Optional, Tuple
from .config import EXCLUDE_AGENT_LIST, DEFAULT_ONLY_TAGS

def agent_clause(only_agent: Optional[str]) -> Tuple[str, List[str]]:
    if only_agent:
        return " AND agent_name = ?", [only_agent]
    if EXCLUDE_AGENT_LIST:
        placeholders = ",".join("?" for _ in EXCLUDE_AGENT_LIST)
        return f" AND (agent_name IS NULL OR agent_name NOT IN ({placeholders}))", EXCLUDE_AGENT_LIST
    return "", []

def tag_clause(only_tags: Optional[List[str]]) -> Tuple[str, List[str]]:
    tags = only_tags if (only_tags and len(only_tags) > 0) else DEFAULT_ONLY_TAGS
    if not tags:
        return "", []
    ors = " OR ".join(["tags LIKE ?"] * len(tags))
    return f" AND ({ors})", [f"%{t}%" for t in tags]
