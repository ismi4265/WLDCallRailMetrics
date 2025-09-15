from fastapi import APIRouter, HTTPException, Request
from typing import Optional, Iterable
from ..core.db import get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _parse_hms_to_seconds(text: str) -> Optional[int]:
    """
    Accepts "HH:MM:SS" or "MM:SS" (optionally with fractional seconds) and returns total seconds.
    """
    try:
        parts = [p.strip() for p in text.split(":")]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = "0", parts[0], parts[1]
        else:
            return None
        total = int(h) * 3600 + int(m) * 60 + int(float(s))
        return total if total >= 0 else None
    except Exception:
        return None


def _to_int_seconds(v) -> Optional[int]:
    """
    Attempts to parse a duration value into integer seconds.
    Handles ints/floats, numeric strings, and HH:MM:SS / MM:SS.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        if v == "":
            return None
        # numeric string?
        try:
            return int(float(v))
        except ValueError:
            pass
        # HH:MM:SS or MM:SS
        if ":" in v:
            return _parse_hms_to_seconds(v)
    return None


def _best_duration_from_payload(payload: dict) -> Optional[int]:
    """
    Look across several plausible keys and return the largest positive duration found.
    This protects against partial events where one field is 0 but another is final.
    """
    candidate_keys: Iterable[str] = (
        "duration",
        "call_length",
        "call_duration",
        "duration_seconds",
        "talk_time",
        "total_duration",
    )
    best = None
    for k in candidate_keys:
        if k in payload:
            secs = _to_int_seconds(payload.get(k))
            if secs is not None and secs > 0 and (best is None or secs > best):
                best = secs
    return best


@router.post("/call-completed")
async def call_completed(req: Request):
    """
    CallRail-like `call.completed` webhook handler (simplified).

    We:
      - Parse duration seconds robustly from several keys and formats.
      - Update duration only if > 0 and greater than what's stored (never overwrite with 0).
      - Optionally update call_status if provided and recognized.
    """
    payload = await req.json()
    ext_id = payload.get("external_id") or payload.get("id")
    if not ext_id:
        raise HTTPException(status_code=400, detail="Missing external_id")

    new_seconds = _best_duration_from_payload(payload)

    incoming_status = payload.get("call_status")
    allowed_status = {"answered", "missed", "no-answer", "voicemail"}
    status_to_set = incoming_status if incoming_status in allowed_status else None

    with get_db() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, duration_seconds FROM calls WHERE external_id = ?", (ext_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Call not found")

        _, current_seconds = row or (None, None)
        current_seconds = int(current_seconds) if current_seconds is not None else None

        sets = []
        args = []

        # Only write duration if it's positive and improves the stored value (prevents 0 clobber).
        if new_seconds is not None and new_seconds > 0:
            if current_seconds is None or current_seconds <= 0 or new_seconds > current_seconds:
                sets.append("duration_seconds = ?")
                args.append(new_seconds)

        if status_to_set is not None:
            sets.append("call_status = ?")
            args.append(status_to_set)

        if not sets:
            # Nothing to update; return OK to avoid retries
            return {"ok": True, "updated": False}

        args.append(ext_id)
        cur.execute(f"UPDATE calls SET {', '.join(sets)} WHERE external_id = ?", args)
        conn.commit()

    return {"ok": True, "updated": True}
