# WLDCallRailMetrics

A FastAPI service that ingests, stores, and reports on CallRail call data.  
Provides metrics, reports, and admin utilities to monitor call performance, agent activity, and conversions.

---

## 🚀 Features

- **Call ingestion** from CallRail webhooks
- **SQLite database** with automatic schema management
- **Metrics endpoints**:
  - Answer rate
  - Conversion rate (with booking tags)
  - Agent scorecards
  - Time-bucketed activity
  - Speed-to-answer
  - Agent occupancy
  - Tag summary
- **Reports endpoints**:
  - Average call time (with per-agent filters)
- **Admin endpoints**:
  - Health check
  - Database diagnostics
  - Backfill derived fields
  - Quick repairs for common issues
  - Dry-run preview tools

---

## 📂 Project Structure

```
app/
  core/         # Config and DB
  routers/      # FastAPI endpoints
  main.py       # App entrypoint
tests/          # Pytest suite
```

---

## ⚙️ Setup

### 1. Clone and install

```bash
git clone https://github.com/ismi4265/WLDCallRailMetrics.git
cd WLDCallRailMetrics
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment

Copy `.env.example` → `.env` and set:

```env
CALLRAIL_API_KEY=your_api_key_here
CALLRAIL_ACCOUNT_ID=your_account_id_here
DB_PATH=./wld_callrail.db

# Optional config
DEFAULT_SLA_SECONDS=30
DEFAULT_CRITICAL_RING=20
```

### 3. Run the API

```bash
uvicorn app.main:app --reload
```

---

## 🔌 Endpoints

### Health

```
GET /health
```

---

### Metrics

```
GET /metrics/answer-rate
GET /metrics/conversion
GET /metrics/agent-scorecard
GET /metrics/time-buckets
GET /metrics/speed-to-answer
GET /metrics/agent-occupancy
GET /metrics/tag-summary
```

---

### Reports

```
GET /reports/avg-call-time-last-week
```

Query params:
- `only_agent=Taylor`
- `only_tags=New Patient`

---

### Admin

```
GET  /admin/diag
POST /admin/backfill-derived
POST /admin/quick-repair
POST /admin/vacuum
GET  /admin/preview-agent
```

---

## 🧪 Testing

Run all tests:

```bash
pytest -q
```

---

## 📊 Example Calls

### Conversion metrics

```bash
curl "http://localhost:8000/metrics/conversion"
```

```json
{
  "answered": 3,
  "booked": 2,
  "booked_rate": 0.67
}
```

### Agent scorecard

```bash
curl "http://localhost:8000/metrics/agent-scorecard"
```

```json
{
  "agents": [
    {"agent": "Taylor", "calls": 1, "answered": 1, "booked": 1, "booked_rate": 1.0},
    {"agent": "Sam", "calls": 1, "answered": 1, "booked": 0, "booked_rate": 0.0}
  ]
}
```

### Average call time (last week, per agent)

```bash
curl "http://localhost:8000/reports/avg-call-time-last-week?only_agent=Taylor"
```

```json
{
  "average_seconds": 180,
  "average_hms": "00:03:00",
  "count": 1,
  "start": "2025-09-06",
  "end": "2025-09-12"
}
```

---

## 📌 Notes

- Tags are critical for filtering.  
  Example: to filter by agent via tags, use `"Agent: Taylor"`.
- The system supports both **agent_name** and **Agent: X** tag matching.
- Admin tools (`quick-repair`, `backfill-derived`) help normalize data if raw CallRail ingestion is incomplete.

---

## 🛠 Roadmap

- Daily/weekly trend endpoints
- Revenue proxy metrics (booked calls as revenue indicator)
- Optional alerts on SLA breaches
- More robust test coverage and CI linting

---