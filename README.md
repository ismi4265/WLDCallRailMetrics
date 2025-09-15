# WLDCallRailMetrics

FastAPI-based service for ingesting and reporting CallRail call data.  
It supports ingesting calls via API/webhooks, storing them in SQLite, and generating metrics/reports (answer rate, conversion, agent scorecards, time buckets, and average call time).

---

## Features

- **Ingest** calls via API or webhook.
- **Reports**
  - Average call time last week (`/reports/avg-call-time-last-week`)
  - Optional filters: `only_agent`, `only_tags`
- **Metrics**
  - Answer rate (`/metrics/answer-rate`)
  - Conversion (booked vs answered) (`/metrics/conversion`)
  - Agent scorecard (`/metrics/agent-scorecard`)
  - Time buckets (histogram by hour or weekday) (`/metrics/time-buckets`)
  - All support filters:  
    - `only_agent=Taylor` (include only Taylor’s calls)  
    - `only_tags=New Patient,Existing Patient` (OR semantics)  
- **Configurable**
  - `EXCLUDE_AGENT_LIST` (e.g., `Taylor`) will globally exclude agents from all metrics unless overridden.
  - `BOOKING_TAGS` (e.g., `"Appointment Booked|AI Generated Scheduled"`) define what counts as a "booked" call.
- **Database**
  - SQLite by default (path set in `.env` as `DB_PATH`).
  - Auto-migrates schema on startup.

---

## Installation

Clone the repo and install dependencies:

```bash
git clone https://github.com/ismi4265/WLDCallRailMetrics.git
cd WLDCallRailMetrics
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

Set environment variables in a `.env` file (loaded by Pydantic `Settings`):

```env
CALLRAIL_API_KEY=dummy
CALLRAIL_ACCOUNT_ID=acct_dummy
DB_PATH=./wld_metrics.db
CORS_ORIGINS=*
EXCLUDE_AGENTS=Taylor
DEFAULT_ONLY_TAGS=
BOOKING_TAGS=Appointment Booked|AI Generated Scheduled
```

Notes:
- `EXCLUDE_AGENTS` is a comma- or pipe-separated list of agents to exclude globally.
- `BOOKING_TAGS` defines which call tags count as "booked".

---

## Running the App

Run the FastAPI server:

```bash
uvicorn app.main:app --reload
```

Server starts at [http://localhost:8000](http://localhost:8000).

Docs available at:
- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Endpoints

### Health
```
GET /health
```
Returns `{"status": "ok"}`

---

### Reports

#### Average Call Time (last week)
```
GET /reports/avg-call-time-last-week
```

**Query params:**
- `only_agent` → filter to one agent
- `only_tags` → comma/pipe separated, OR semantics
- Excludes `duration_seconds <= 0` and non-answered calls.

**Response:**
```json
{
  "start": "2025-09-06",
  "end": "2025-09-12",
  "average_seconds": 170.0,
  "average_hms": "00:02:50",
  "note": "Rolling 7-day window including today."
}
```

---

### Metrics

#### Answer Rate
```
GET /metrics/answer-rate
```
**Response:**
```json
{
  "answered": 10,
  "total": 15,
  "answer_rate": 0.6667
}
```

---

#### Conversion
```
GET /metrics/conversion
```
**Response:**
```json
{
  "answered": 3,
  "booked": 2,
  "booked_rate": 0.6667
}
```

Supports filters:
- `only_agent`
- `only_tags`

---

#### Agent Scorecard
```
GET /metrics/agent-scorecard
```

**Response:**
```json
{
  "agents": [
    {
      "agent": "Taylor",
      "calls": 1,
      "answered": 1,
      "booked": 1,
      "booked_rate": 1.0
    },
    {
      "agent": "Sam",
      "calls": 2,
      "answered": 2,
      "booked": 1,
      "booked_rate": 0.5
    }
  ]
}
```

---

#### Time Buckets
```
GET /metrics/time-buckets
```

**Query params:**
- `by=hour` (default) → 0–23
- `by=weekday` → Mon=0..Sun=6
- `start`, `end` → ISO dates
- `only_agent`, `only_tags`

**Response:**
```json
{
  "by": "hour",
  "start": "2025-09-06",
  "end": "2025-09-12",
  "buckets": [
    { "bucket": 0, "count": 4 }
  ],
  "grid": [4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
}
```

---

### Ingest

#### POST /ingest/call
```json
{
  "id": "call123",
  "agent_name": "Taylor",
  "call_status": "answered",
  "call_type": "inbound",
  "company_id": "co1",
  "duration_seconds": 180,
  "tags": "New Patient,AI Generated Scheduled",
  "created_at": "2025-09-10T12:30:00"
}
```

---

### Webhooks

Webhook handler at:
```
POST /webhooks/call-completed
```

Expects CallRail JSON payload → inserts/updates DB row.

---

## Testing

Run all tests with:

```bash
pytest -q
```

- Seed data in `tests/conftest.py` auto-creates test calls.
- Tests cover all endpoints (`health`, `metrics`, `reports`, `webhooks`).
- Make sure `.env.test` points to a temp DB.

---

## Development Notes

- **Filters precedence**:  
  - `EXCLUDE_AGENTS` always applies, unless overridden with `only_agent`.  
  - `only_tags` and `BOOKING_TAGS` are substring matches (`tags LIKE '%term%'`).
- **Zero-duration & unanswered calls** are excluded from averages.
- **Time buckets** return both a dense `grid` and a sparse `buckets` list.

---

## Example Queries

```bash
# Average call time for Taylor only
curl "http://localhost:8000/reports/avg-call-time-last-week?only_agent=Taylor"

# Conversion rate for New Patients
curl "http://localhost:8000/metrics/conversion?only_tags=New Patient"

# Time buckets by weekday, only answered Existing Patients
curl "http://localhost:8000/metrics/time-buckets?by=weekday&only_tags=Existing Patient"
```
