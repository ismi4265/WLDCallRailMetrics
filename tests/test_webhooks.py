from fastapi.testclient import TestClient

from app.core.db import get_db   # <-- absolute import
from app.main import app         # <-- absolute import


@router.post("/call-completed")
async def call_completed(req: Request):
    """
    CallRail `call.completed` webhook handler (simplified).

    Expected keys that we actually care about here:
      - id / external_id: external identifier we use to find the row
      - duration: seconds (string or number). Only persist if > 0.
      - call_status: often "answered" on completed; if provided we'll write it.
    """
    payload = await req.json()
    ext_id = payload.get("external_id") or payload.get("id")
    if not ext_id:
        raise HTTPException(status_code=400, detail="Missing external_id")

    # Parse duration safely; write only if > 0
    raw = payload.get("duration")
    duration_seconds = None
    if raw is not None:
        try:
            duration_seconds = int(float(raw))
        except (TypeError, ValueError):
            duration_seconds = None

    # If the webhook explicitly says answered, keep it; otherwise leave as-is
    incoming_status = payload.get("call_status")
    status_to_set = incoming_status if incoming_status in {"answered", "missed", "no-answer", "voicemail"} else None

    with get_db() as conn:
        cur = conn.cursor()

        # Always ensure the row exists; if not, bail early
        cur.execute("SELECT id, duration_seconds FROM calls WHERE external_id = ?", (ext_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Call not found")

        # Build update dynamically so we don't overwrite good values
        sets = []
        args = []

        if duration_seconds is not None and duration_seconds > 0:
            sets.append("duration_seconds = ?")
            args.append(duration_seconds)

        if status_to_set is not None:
            sets.append("call_status = ?")
            args.append(status_to_set)

        if not sets:
            # Nothing to write; return OK to avoid retry storms
            return {"ok": True, "updated": False}

        args.append(ext_id)
        sql = f"UPDATE calls SET {', '.join(sets)} WHERE external_id = ?"
        cur.execute(sql, args)
        conn.commit()

    return {"ok": True, "updated": True}
