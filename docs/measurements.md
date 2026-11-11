# Measurements

This file records how the numbers in the README were produced. They are local demo measurements, not production benchmarks.

## Environment

| Item | Value |
|---|---|
| Date | 2026-11-11 |
| OS | Ubuntu 24.04.4 LTS |
| CPU | 12 vCPU |
| RAM | 7.6 GB |
| Docker | 29.1.3 |
| Python | 3.12.3 |
| Node.js | 20.20.2 |
| PostgreSQL | 16-alpine |
| Backend image | `capi-platform-demo-backend` |

## Test suite

```bash
cd capi-platform/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q \
  --cov=app.services.network \
  --cov=app.schemas \
  --cov=app.services.auth \
  --cov=app.services.demo \
  --cov-report=term
```

Result:

```text
64 passed
TOTAL  259 statements  16 missed  94% coverage
```

## Demo startup

Cold start, including the Docker image build:

```bash
cd capi-platform
time docker compose -f docker-compose.demo.yml up -d --build
# wait for http://localhost:8001/healthz
```

Result: **63 s** end-to-end on the machine above.

Restart with images already built:

```bash
docker compose -f docker-compose.demo.yml down
time docker compose -f docker-compose.demo.yml up -d
```

Result: **9 s** until `/healthz` returned 200.

## Backend image size

```bash
docker images capi-platform-demo-backend --format '{{.Size}}'
```

Result: **310 MB**.

## Local API latency

100 sequential requests, measured with `curl -w '%{time_total}'`, then sorted for percentiles:

| Endpoint | Mean | p50 | p95 | Max |
|---|---:|---:|---:|---:|
| `GET /healthz` | 2.3 ms | 2.0 ms | 3.7 ms | 5.2 ms |
| `GET /api/clusters/` (authenticated) | 6.0 ms | 5.5 ms | 9.6 ms | 13.4 ms |

These numbers include Python, the HTTP stack and the PostgreSQL-backed demo data. The test suite uses SQLite; the demo uses PostgreSQL. They are not a production capacity claim.

## Incident regression

```bash
pytest tests/test_network.py -q
```

The suite checks nine forbidden node CIDR classes, overlap with existing subnets, the free-CIDR suggestion, IPv6 rejection, and the server-side HTTP 400 path.
