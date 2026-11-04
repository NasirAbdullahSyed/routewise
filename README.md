# Routewise

React + Django weather-aware route comparison. Enter two cities, departure time, load weight, and checkpoint spacing to compare three routes using arrival-time weather and load-dependent risk.

## Run locally

Requires Node.js 20.19+ (or 22.12+) and Python 3.10+. The example uses Python 3.12; substitute another supported interpreter if needed.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm ci
npm run build
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000. No database or API keys are required for local assessment use. The initial view is a labeled synthetic sample; **Find routes** requests live data. Map tiles and fonts still require internet access in sample mode.

For frontend development, leave Django running and run `npm run dev` in a second terminal. Vite proxies `/api` to Django.

## Risk rules

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | <25 | 25–<35 | 35–<45 | 45–<55 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–<0.25 | 0.25–<0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–<1.0 | 1.0–<2.0 | 2.0–3.0 | >3.0 |

Shared rain/snow boundaries use the higher class; exactly 1 inch rain and 3 inches snow remain Severe. Wind ≥55 mph is No Travel for every load; wind ≥45 mph with load >30,000 lb is No Travel; wind ≥35 mph with load >40,000 lb is at least Severe. The worst applicable condition wins. Rain includes showers; snowfall units are converted when needed.

Each interval uses the worse of its endpoint risks, weighted by actual interval length. Recommendations exclude No Travel routes, then minimize Severe miles, High miles, distance-weighted average risk, and travel time, in that order. Average risk uses Low=0 through No Travel=4. If every route is blocked, no recommendation is made.

## Map and forecasts

- OSRM supplies road routes, supplemented by labeled via-waypoint routes if needed. An error is returned if three distinct routes cannot be found.
- Checkpoints follow road geometry every 10, 25, or 50 miles, including both endpoints. ETAs use segment durations. Preceding-hour precipitation forecasts use the hour ending at or after arrival.
- All routes and checkpoints are visible together. Select a route to emphasize its markers and update the weather table; map popups support mouse and keyboard.
- Editing keeps the displayed results labeled with their submitted trip. Cancel restores the last submitted fields and stops a pending update. On mobile, the planner appears before the map and results.
- Ranking help and route limitations are available in compact disclosures; linked data credits are shown on the map.
- The 0–48 hour slider changes corridor forecasts without changing arrival-time route scores or making another planning request.
- Unique fixed-color forecast cells cover the roads and a one-cell lateral buffer. Nominal cell size starts at 10 miles and grows as needed to stay within 240 cells; the current size is displayed. Zoom and overlapping routes do not add risk intensity.
- Weather is batched and cached for 15 minutes; city matches are cached for 24 hours. Transient provider errors have one retry. Missing live data is never replaced with synthetic data.

## Verify

```sh
.venv/bin/python backend/manage.py test routing
.venv/bin/python backend/manage.py check
npm run build
```

## Deploy

### Vercel

Import the repository into a personal Vercel project. The included configuration serves the React build from the CDN and `/api` through the Django Python function. Set `DJANGO_DEBUG=false`, a random `DJANGO_SECRET_KEY`, and `ALLOWED_HOSTS` to the project's deployment hostname (or `.vercel.app` for Vercel preview and production domains). No database is required. Planning requests have a 300-second maximum duration; provider availability and free-tier quotas still apply.

### Docker

The Dockerfile builds React and serves it through Django, WhiteNoise, and Gunicorn.

```sh
cp .env.example .env
# Edit .env with a random secret and the deployment hostname.
docker build -t routewise .
docker run --rm -p 8000:8000 --env-file .env routewise
```

Set `PORT` if required by the host. `/api/health` is the health check. Environment variables are read directly; `.env` is not automatically loaded outside the Docker command above.

## Limits and providers

From and To offer city suggestions after three characters, with region/country labels and arrow-key/Enter selection. Selected locations keep their exact coordinates, including after swapping endpoints. If you submit an unselected city name, the first geocoder match is used; resolved names are shown for review. Departure is limited to the next 48 hours, load to 100,000 lb, and plans to 650 checkpoints. Weather is hourly and sampled at checkpoint/cell centers; cells do not represent exact storm boundaries. The cache is per-process memory.

Routing uses a driving profile, without truck restrictions, traffic, road closures, rest breaks, or hours-of-service modeling. Public providers have availability and usage limits and may need replacement for wider deployment.

Providers: [OSRM](https://project-osrm.org/docs/v5.24.0/api/), [Open-Meteo weather](https://open-meteo.com/en/docs), [Open-Meteo geocoding](https://open-meteo.com/en/docs/geocoding-api), [Esri basemap](https://www.arcgis.com/home/item.html?id=8b3d38c0819547faa83f7b7aca80bd76), and [OpenStreetMap data](https://www.openstreetmap.org/copyright).
