from fastapi import APIRouter, Query
from ..core.db import get_db, rows_to_list
from ..core.config import DATE_COL

router = APIRouter(prefix="/debug", tags=["debug"])

@router.get("/db-stats")
def db_stats():
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()
        minmax = conn.execute(f"SELECT MIN({DATE_COL}) AS min_date, MAX({DATE_COL}) AS max_date FROM calls").fetchone()
        return {"rows": row["n"], "min_date": minmax["min_date"], "max_date": minmax["max_date"]}
    finally:
        conn.close()

@router.get("/dates")
def dates(limit: int = Query(30, ge=1, le=365)):
    conn = get_db()
    try:
        rows = conn.execute(
            f"""
            SELECT {DATE_COL} AS day, COUNT(*) AS calls,
                   ROUND(AVG(COALESCE(duration_seconds,0)), 2) AS avg_secs
            FROM calls
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()
