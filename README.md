# WLD CallRail Metrics API

A FastAPI application to ingest call data from the [CallRail API](https://apidocs.callrail.com/), store it in SQLite, and generate metrics/reports.

## 🚀 Features
- Ingest calls from CallRail API (by date range or last week).
- Store normalized call data in SQLite.
- Compute metrics:
  - Summary (call counts, answered, average duration).
  - Grouped by company, source, tags.
  - Duration buckets.
- Reports:
  - **Average call time over the last 7 days.**
- 🔒 Agent filters:
  - Globally exclude agents (via `.env`).
  - Override per request with `?only_agent=Name`.
- 🏷 Tag filters:
  - Globally restrict to tags (via `.env`).
  - Override per request with `?only_tags=Tag1,Tag2`.

## 📂 Project structure
WLDCallRailMetrics/
├── app/
│ └── main.py # FastAPI app
├── requirements.txt
├── Dockerfile
├── .github/workflows/ci.yml
├── .env.example
└── README.md

bash

## ⚙️ Setup

1. **Clone repo**
   ```bash
   git clone https://github.com/ismi4265/WLDCallRailMetrics.git
   cd WLDCallRailMetrics

2. **Create virtual environment**
'''bash
python3 -m venv .venv
source .venv/bin/activate

3. **Install dependencies**
'''bash
pip install -r requirements.txt


4. **Configure environment**
'''bash 
Copy .env.example → .env and fill in values:

env
bash''
CALLRAIL_API_KEY=your_api_key
CALLRAIL_ACCOUNT_ID=your_account_id
DB_PATH=callrail_metrics.db
CORS_ORIGINS=*
EXCLUDE_AGENTS=Taylor
DEFAULT_ONLY_TAGS=Existing Patient,New Patient


## ▶️ Running


**Local**
bach''
uvicorn app.main:app --reload --port 8000
App runs at: http://localhost:8000

**Docker**
Build:
'''bash
docker build -t wld-callrail:dev .

Run with .env:

'''bash
docker run --rm -p 8000:8000 --env-file .env wld-callrail:dev


**GitHub Actions**
A CI workflow is included at .github/workflows/ci.yml.

## 🧪 Endpoints

**Health**
'''bash
curl http://localhost:8000/health

**Ingest last week**
'''bash
curl -X POST http://localhost:8000/ingest/last-week

**Metrics summary**
'''bash
curl http://localhost:8000/metrics/summary

**Report: Avg call time last week**
'''bash
curl http://localhost:8000/reports/avg-call-time-last-week


## 🎯 Filters
**Exclude agent(s) globally**


Configured via .env:

env

EXCLUDE_AGENTS=Taylor


**Include only one agent (per request)**

'''bash
curl "http://localhost:8000/reports/avg-call-time-last-week?only_agent=Taylor"


**Restrict to tags (per request)**
Note: Spaces must be URL-encoded as %20.

'''bash
curl "http://localhost:8000/reports/avg-call-time-last-week?only_tags=Existing%20Patient,New%20Patient"


Or safer with --data-urlencode:

'''bash
curl --get "http://localhost:8000/reports/avg-call-time-last-week" \
  --data-urlencode "only_tags=Existing Patient,New Patient"


**Combine agent + tags**

'''bash
curl --get "http://localhost:8000/reports/avg-call-time-last-week" \
  --data-urlencode "only_agent=Taylor" \
  --data-urlencode "only_tags=Existing Patient,New Patient"


## 🛠 Debugging
Check what’s in the database:

'''bash
curl http://localhost:8000/debug/db-stats
curl http://localhost:8000/debug/dates


## 📜 License
MIT