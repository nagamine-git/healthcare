# Healthcare Dashboard — Self-Hosted Garmin + Apple Health Analytics with AI Coaching

A **self-hosted, single-user health dashboard** that turns your **Garmin Connect** and
**Apple Health** data into a daily "how am I doing today?" score, evidence-based wellbeing
alerts, and **LLM-generated coaching** — served privately over your own
[Tailscale](https://tailscale.com) network.

It reads the data your wearables already collect (sleep, HRV, SpO2, respiration, Body
Battery, Training Readiness, resting heart rate, weight, body fat, steps, stress) and
answers three questions every morning:

1. **What state am I in today?** — a 0–100 condition score across sleep, autonomic
   recovery (HRV), energy, training load, body composition, and physiology.
2. **What should I watch out for?** — rule-based medical alerts (sleep debt, HRV decline,
   low blood-oxygen, irregular circadian rhythm, medication-overuse-headache risk,
   barometric migraine triggers) grounded in published research.
3. **What should I do?** — concise, personalized daily actions from Claude, weighted by
   your goals and today's recovery.

> ⚠️ **Disclaimer.** This is a personal quantified-self tool, **not a medical device**.
> Scores, alerts, and AI advice are informational only and are **not diagnosis or
> treatment**. Wrist-based optical sensors (SpO2, respiration) are noisy; alerts are
> deliberately conservative and framed as "reasons to pay attention / see a doctor,"
> never as a clinical verdict. Consult a qualified professional for medical decisions.

---

## Why this exists

Wearables collect an enormous amount of data and then bury the useful parts. Garmin's app
shows you a sleep score but not "your blood-oxygen has dropped three nights running."
Apple Health stores everything but interprets nothing. This project is the missing
**interpretation layer**: it joins both sources, scores them against personalized targets
and published clinical norms, and produces a short, actionable readout — privately, on
hardware you control, with no third-party health cloud.

## Features

- **Daily condition score (0–100)** across sleep, HRV, energy (Body Battery), training
  load (ACWR), weight, and body fat — each with an achievement curve toward an ideal band.
- **Physiology trends** extracted from Garmin sleep data: **blood oxygen (SpO2, avg +
  lowest), respiration rate, nocturnal resting HR, sleep midpoint (circadian regularity),
  Training Readiness, fitness age** — with 28-day sparklines and week-over-week deltas.
- **Evidence-based wellbeing alerts** — chronic sleep deficit (Belenky 2003), HRV chronic
  decline (Plews 2013), recovery failure, blood-oxygen desaturation (apnea screening),
  elevated respiration vs. baseline, low Training Readiness streaks, irregular circadian
  rhythm (circular statistics), medication-overuse-headache risk (ICHD-3), and barometric
  pressure migraine triggers.
- **LLM daily coaching** (Anthropic Claude) — 1–3 concrete actions per day, personalized
  to your goals, equipment, injury history, and Karvonen heart-rate zones, with optional
  Google Calendar scheduling.
- **Instrument-cluster status lamps** — a car-dashboard-style icon row giving an at-a-glance
  read of every metric, with tap-to-expand detail.
- **Life-domain scoring** — extend beyond health to track meditation, learning, work, and
  more, with adjustable importance weights.
- **Private by default** — runs in Docker on your machine, exposed only inside your
  Tailscale tailnet via a `tailscale serve` sidecar (HTTPS, no public ingress).

## Architecture

```
[iPhone Health Auto Export] ──POST/JSON──▶ [FastAPI /ingest/health-auto-export]
[Garmin Connect] ◀──python-garminconnect── [APScheduler, hourly]
                                                   │
                                                   ▼
                                   [SQLite (WAL) + scoring + Claude LLM]
                                                   │
[Browser via tailnet HTTPS] ── tailscale serve sidecar (443→80) ── nginx → FastAPI
```

**Stack**

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, APScheduler, Anthropic SDK, python-garminconnect |
| Frontend | React, Vite, TanStack Query, Tailwind CSS, Recharts, lucide-react |
| Data | SQLite (WAL) |
| Deploy | Docker Compose (`backend`, `frontend`, `tailscale` sidecar) |
| Secrets | 1Password CLI (`op run`) or any `.env` |

## The science

Thresholds split into two kinds, and the code keeps them separate:

- **Clinical/physiological constants** (fixed for everyone): SpO2 normal ≥95% / hypoxemia
  <90%; resting respiration 12–18 brpm; ACWR sweet spot 0.8–1.3; HRV evaluated as an
  individual z-score against a 28-day baseline rather than absolute values.
- **Personal targets** (configurable per user): target weight, body fat, age, sex, height,
  resting heart rate, sleep goal, caffeine half-life, protein target.

Notable correctness details: the **sleep midpoint** (a standard circadian marker) is a
*cyclic* quantity, so regularity is computed with **circular statistics** — a naive linear
standard deviation breaks for anyone whose midpoint crosses midnight. Medication-overuse
risk counts **distinct medication days** (per ICHD-3), not doses. See
[`docs/superpowers/specs/`](./docs/superpowers/specs/) for the design rationale and
[SPEC.md](./SPEC.md) for the full spec.

## Quick start

**Prerequisites:** Docker, a Garmin Connect account, an Anthropic API key, a Tailscale
account, and (optionally) an iPhone with [Health Auto Export](https://apps.apple.com/app/id1115567069)
for Apple Health metrics.

```bash
# 1. Configure secrets and personal profile
cp .env.example .env        # then edit: ANTHROPIC_API_KEY, GARMIN_*, TS_AUTHKEY, HAE_INGEST_TOKEN
                            # and your profile: USER_AGE, TARGET_WEIGHT_KG, WEATHER_LATITUDE, ...

# 2. Build & start (backend + frontend + tailscale sidecar)
docker compose up -d --build

# 3. First Garmin login (interactive, handles MFA)
docker compose exec backend python -m app.cli garmin-login

# 4. Open the dashboard inside your tailnet
#    https://<hostname>.<tailnet>.ts.net
```

> The repo includes 1Password-based helper scripts (`bin/up.sh`, `bin/verify.sh`) for
> resolving secrets via `op run`. If you don't use 1Password, a plain `.env` works the
> same way.

### Personalize your profile

Your biometric targets and training profile live in `backend/app/config.py` as an **example
profile** and are overridable via environment variables. Set at least:

| Variable | Meaning |
|---|---|
| `USER_AGE`, `USER_SEX`, `USER_HEIGHT_CM`, `USER_RESTING_HR` | drives Karvonen HR zones & coaching |
| `TARGET_WEIGHT_KG`, `TARGET_BODY_FAT_PCT` | body-composition scoring |
| `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, `WEATHER_LOCATION_LABEL` | barometric migraine monitoring |
| `MEDITATION_TARGET_MIN` | meditation life-domain goal |

### Apple Health (optional)

In [Health Auto Export](https://apps.apple.com/app/id1115567069), add a REST API automation:

- URL: `https://<hostname>.<tailnet>.ts.net/ingest/health-auto-export`
- Header `Authorization: Bearer <your HAE_INGEST_TOKEN>`
- Data Type: Health Metrics (All), Format: JSON v2, Summarize: ON, Cadence: 6 h

## Development

```bash
# Backend (Python 3.12)
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.' --group dev
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app/ tests/

# Frontend
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build
```

## CLI

`docker compose exec backend python -m app.cli <command>`

| Command | Purpose |
|---|---|
| `garmin-login` | Interactive Garmin Connect login (for MFA) |
| `sync-garmin` | Manual pull from Garmin |
| `recompute [YYYY-MM-DD]` | Recompute a day's score (default: today) |
| `regenerate-advice [YYYY-MM-DD]` | Force-regenerate LLM advice |

## Tailscale ACL

To use the `tag:healthcare` auth-key tag, add a `tagOwner` in your tailnet ACL:

```json
{
  "tagOwners": {
    "tag:healthcare": ["your-email@example.com"]
  }
}
```

## License

[MIT](./LICENSE) © 2026 nagamine-git

---

<sub>Keywords: self-hosted health dashboard, Garmin Connect API, Apple Health integration,
HRV tracking, sleep analysis, SpO2 monitoring, Body Battery, Training Readiness, quantified
self, FastAPI, React, Tailscale, Anthropic Claude, LLM health coaching, circadian rhythm,
wearable data analytics, personal health record, open source health app.</sub>
