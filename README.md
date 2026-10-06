# BDA mini — CyberShield AI

**CyberShield AI** is a Big Data Cyber Attack Detection & Security-Analytics
platform built on the NSL-KDD benchmark. It wires together a full big-data
stack — Hadoop/HDFS, Kafka, Spark (batch training + Structured Streaming),
PostgreSQL, Redis — behind a FastAPI REST + WebSocket backend and a Next.js SOC
dashboard.

```
raw NSL-KDD  ──▶  preprocessing (Spark)  ──▶  model training (Spark MLlib)
                                                      │
        live events  ──▶  Kafka  ──▶  Structured Streaming scorer  ──▶  alerts
                                                      │
                                    PostgreSQL / Redis  ◀──  FastAPI  ──▶  Next.js UI
```

---

## Repository layout

| Path                     | What it holds                                                        |
|--------------------------|----------------------------------------------------------------------|
| `backend/`               | FastAPI app: REST endpoints, WebSocket feed, services, DB models     |
| `frontend/`              | Next.js 15 SOC dashboard (React 19, Tailwind, Recharts, three.js)    |
| `ml/`                    | Spark MLlib training, preprocessing and held-out evaluation          |
| `streaming/`             | Kafka producers/consumers, event schemas, Structured Streaming job   |
| `data/`                  | Raw + processed datasets and the NSL-KDD downloader                  |
| `infrastructure/`        | Hadoop, Kafka, Spark, PostgreSQL, Redis configuration                |
| `docker-compose.yml`     | One-command full stack (HDFS, Kafka, Spark, Postgres, Redis, apps)   |

---

## Prerequisites

- **Python 3.11+** (3.10 also works for local ML/streaming runs)
- **Node.js 18+** and npm
- **Docker Desktop** + Docker Compose (for the full stack)
- **Java 8/11/17** (bundled with `pyspark`; needed for Spark)

> The big data layer (HDFS/Kafka/Spark cluster) is optional for a quick demo:
> the backend has a built-in **demo mode** and the ML/streaming scripts run on
> a fully **local** Spark session (`local[*]`) with no cluster.

---

## Quick start (full stack with Docker)

```bash
cp .env.example .env          # optional — safe defaults are inlined
docker compose up -d --build
```

Then open:

| Service          | URL                                |
|------------------|------------------------------------|
| Frontend (SOC)   | http://localhost:3000              |
| Backend API docs | http://localhost:8000/docs         |
| Health probe     | http://localhost:8000/health       |
| Spark Master UI  | http://localhost:8080              |
| HDFS NameNode UI | http://localhost:9870              |

Stop everything with `docker compose down` (add `-v` to also wipe volumes).

---

## Manual setup (without Docker)

### 1. Python environment

```bash
cd cybershield-ai
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

pip install -r backend/requirements.txt
pip install -r ml/requirements.txt
pip install -r streaming/requirements.txt
```

### 2. Data + model pipeline

```bash
python data/download_dataset.py                 # fetch KDDTrain+/KDDTest+ into data/raw
python -m ml.preprocessing.preprocess           # -> data/processed/{train,test}.parquet
python ml/training/train_model.py --quick 30000 # trains RF/DT/GBT/LR, exports artifacts to ml/models
python -m ml.evaluation.evaluate --quick 20000  # held-out re-verification -> ml/models/evaluation_report.json
```

Training writes JSON metadata + a portable `sklearn_model.pkl` mirror on every
host. The native Spark `best_model/` directory additionally saves on Docker /
Linux; on a bare Windows dev host the Spark binary save needs `hadoop.dll` and
is skipped gracefully (evaluation then falls back to the sklearn mirror).

### 3. Structured Streaming job

Requires the Kafka + HDFS stack from `docker compose`. Then:

```bash
python -m streaming.spark_jobs.attack_detection --trigger-seconds 5
```

It consumes `network-events`, scores each event (loaded Spark model, or a
heuristic fallback when no model is present) and publishes to
`security-events` / `alerts` (and PostgreSQL).

### 4. Backend

Point `.env` at your Postgres/Redis/Kafka (or just run the infra containers),
then:

```bash
uvicorn app.main:app --reload --port 8000     # run from inside backend/
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev                                    # http://localhost:3000
```

---

## Configuration

All runtime settings are environment-driven (see [`.env.example`](.env.example)):
database/Redis/Kafka URLs, HDFS NameNode, Spark master, backend host/port, CORS
origins, and the frontend's `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL`.

---

## Notes for running on a second machine

- Heavy / regenerable folders are **git-ignored** and must be rebuilt after a
  clone: `.venv/`, `frontend/node_modules/`, `frontend/.next/`, `data/raw/*`,
  `data/processed/*`, and the binary model files (`ml/models/*.pkl|joblib|onnx|parquet`).
- After cloning, re-run the **Quick start** or the **Manual setup** steps to
  recreate them.
- The committed JSON artifacts under `ml/models/` (metrics, confusion matrix,
  feature importance, metadata) are small and give you the training results
  without a re-run.

---

*`# BDA-mini`*
