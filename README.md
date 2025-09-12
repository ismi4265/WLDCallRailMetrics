# WLD CallRail Metrics API

FastAPI microservice to ingest CallRail call data and expose simple metrics.

## Features
- Secure config via environment variables (`.env`)
- Ingest calls with relative pagination
- SQLite persistence (easy to swap for Postgres)
- Metrics endpoints (summary, by company/source/tag, duration buckets)
- CORS middleware (configurable)

---

## Prerequisites
- Python 3.10+
- A CallRail **API key** and **Account ID**

## Setup

1) **Clone & enter**
```bash
git clone https://github.com/ismi4265/WLDCallRailMetrics.git
cd WLDCallRailMetrics

## Docker

### Build locally
```bash
docker build -t wld-callrail:dev .
