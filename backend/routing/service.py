import math
from datetime import datetime, timedelta, timezone
from .providers import (
    geocode,
    route_options,
    sample_route,
    weather,
    weather_at,
    ProviderError,
)
from .risk import classify, summarize, rank_key
from .corridor import corridor_cells


def demo_routes():
    paths = [
        [
            [-87.63, 41.88],
            [-87.40, 41.60],
            [-87.10, 41.20],
            [-86.85, 40.75],
            [-86.5, 40.25],
            [-86.16, 39.77],
        ],
        [
            [-87.63, 41.88],
            [-87.85, 41.45],
            [-87.70, 40.90],
            [-87.45, 40.35],
            [-86.85, 40.05],
            [-86.16, 39.77],
        ],
        [
            [-87.63, 41.88],
            [-87.10, 41.65],
            [-86.65, 41.25],
            [-86.20, 40.85],
            [-85.95, 40.25],
            [-86.16, 39.77],
        ],
    ]
    routes = []
    from .providers import haversine

    for i, coords in enumerate(paths):
        lengths = [haversine(a, b) for a, b in zip(coords, coords[1:])]
        distance = sum(lengths)
        seconds = distance / 24 * [1, 1.03, 0.97][i]
        routes.append(
            {
                "geometry": {"coordinates": coords},
                "distance": distance,
                "duration": seconds,
                "legs": [
                    {
                        "annotation": {
                            "duration": [x / distance * seconds for x in lengths]
                        }
                    }
                ],
            }
        )
    return routes


def demo_weather(point, timestamp, base):
    # Explicitly synthetic storm over the east side of the sample corridor.
    storm = math.exp(
        -((point["lat"] - 40.8) ** 2 / 0.3 + (point["lon"] + 86.65) ** 2 / 0.28)
    )
    pulse = 0.85 + 0.15 * math.cos((timestamp - base) / 3600 / 5)
    return {
        "wind": 15 + 34 * storm * pulse,
        "rain": 0.03 + 0.32 * storm * pulse,
        "snow": 0,
    }


def build_plan(data):
    now = datetime.now(timezone.utc)
    try:
        load = float(data.get("load", 30000))
        interval = int(data.get("interval", 25))
        departure = datetime.fromisoformat(
            str(data["departure"]).replace("Z", "+00:00")
        )
        if departure.tzinfo is None:
            raise ValueError()
        if (
            not math.isfinite(load)
            or not 0 <= load <= 100000
            or interval not in [10, 25, 50]
        ):
            raise ValueError()
        if not now - timedelta(minutes=5) <= departure <= now + timedelta(hours=48):
            raise ValueError()
        origin_text, destination_text = (
            str(data["origin"]).strip(),
            str(data["destination"]).strip(),
        )
        if not 2 <= len(origin_text) <= 200 or not 2 <= len(destination_text) <= 200:
            raise ValueError()
        demo = data.get("demo", False)
        if not isinstance(demo, bool):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError(
            "Enter two cities, a departure within the next 48 hours, a load from 0 to 100,000 lb, and a 10, 25, or 50 mile interval."
        )
    base = int(now.timestamp() // 3600 * 3600)
    if demo:
        origin = {
            "name": "Chicago, Illinois, United States",
            "lat": 41.88,
            "lon": -87.63,
        }
        destination = {
            "name": "Indianapolis, Indiana, United States",
            "lat": 39.77,
            "lon": -86.16,
        }
        raw_routes = demo_routes()
    else:
        origin = geocode(origin_text, data.get("origin_place"))
        destination = geocode(destination_text, data.get("destination_place"))
        raw_routes = route_options(origin, destination)
    samples = [sample_route(r, interval * 1609.344) for r in raw_routes]
    if sum(map(len, samples)) > 650:
        raise ValueError(
            "This trip has too many checkpoints. Select a wider interval or a shorter trip."
        )
    corridor = corridor_cells(raw_routes)
    forecasts = (
        {} if demo else weather([p for route in samples for p in route] + corridor)
    )

    def at(p, timestamp):
        return (
            demo_weather(p, timestamp, base)
            if demo
            else weather_at(
                forecasts[(round(p["lat"], 4), round(p["lon"], 4))], timestamp
            )
        )

    routes = []
    for i, (raw, points) in enumerate(zip(raw_routes, samples)):
        for p in points:
            timestamp = departure.timestamp() + p["elapsed"]
            p.update(at(p, timestamp))
            p["eta"] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
            p["risk"] = classify(p["wind"], p["rain"], p["snow"], load)
        routes.append(
            {
                "id": i,
                "name": f"Route {i+1}",
                "via": raw.get("via", False),
                "coordinates": raw["geometry"]["coordinates"],
                "checkpoints": points,
                "summary": summarize(
                    points, raw["distance"] / 1609.344, raw["duration"]
                ),
            }
        )
    ordered = sorted(routes, key=rank_key)
    recommendation = next(
        (r["id"] for r in ordered if not r["summary"]["blocked"]), None
    )
    for p in corridor:
        p["forecast"] = []
        for hour in range(49):
            w = at(p, base + hour * 3600)
            p["forecast"].append(
                {**w, "risk": classify(w["wind"], w["rain"], w["snow"], load)}
            )
    return {
        "origin": origin,
        "destination": destination,
        "departure": departure.isoformat(),
        "load": load,
        "interval": interval,
        "routes": ordered,
        "recommended_id": recommendation,
        "corridor": corridor,
        "corridor_resolution_miles": corridor[0]["cell_miles"],
        "forecast_start": datetime.fromtimestamp(base, timezone.utc).isoformat(),
        "demo": demo,
        "generated_at": now.isoformat(),
        "warnings": [
            "Road routing uses a driving profile; truck height, axle, hazmat and road restrictions are not checked.",
            "Travel times exclude traffic, breaks and hours-of-service requirements.",
        ],
    }
