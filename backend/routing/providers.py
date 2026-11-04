import math
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.cache import cache


class ProviderError(Exception):
    pass


def fetch(url, params):
    try:
        # One retry for transient public-provider failures; never silently
        # replace missing live forecasts with sample data.
        retry = Retry(
            total=1,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=False,
        )
        with requests.Session() as session:
            session.mount("https://", HTTPAdapter(max_retries=retry))
            r = session.get(
                url,
                params=params,
                timeout=(5, 35),
                headers={"User-Agent": "RoutewiseAssessment/1.0"},
            )
        r.raise_for_status()
        result = r.json()
        if isinstance(result, dict) and result.get("error"):
            raise ProviderError("The weather provider could not process this trip.")
        return result
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(
            "A map or weather provider is unavailable. Please retry, or use the sample trip."
        ) from exc


def search_locations(query):
    key = "locations:" + hashlib.sha256(query.casefold().encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = fetch(
        os.getenv("GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"),
        {"name": query, "count": 6, "language": "en", "format": "json"},
    )
    results = []
    for place in data.get("results", []):
        region = ", ".join(
            dict.fromkeys(filter(None, [place.get("admin1"), place.get("country")]))
        )
        name = ", ".join(
            dict.fromkeys(
                filter(None, [place["name"], place.get("admin1"), place.get("country")])
            )
        )
        results.append(
            {
                "id": place["id"],
                "city": place["name"],
                "region": region,
                "name": name,
                "lat": place["latitude"],
                "lon": place["longitude"],
            }
        )
    cache.set(key, results, 300)
    return results


def geocode(city, selected=None):
    if selected is not None:
        # A selected suggestion carries its coordinates so another name lookup
        # cannot silently choose a different city with the same name.
        try:
            lat, lon = float(selected["lat"]), float(selected["lon"])
            if (
                selected["name"] != city
                or not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -85 <= lat <= 85
                or not -180 <= lon <= 180
            ):
                raise ValueError()
            return {"name": city, "lat": lat, "lon": lon}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(
                "Choose a valid location suggestion or enter the city again."
            )
    key = "city:" + hashlib.sha256(city.lower().strip().encode()).hexdigest()
    if (found := cache.get(key)) is not None:
        return found
    result = fetch(
        os.getenv("GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"),
        {"name": city, "count": 1, "language": "en", "format": "json"},
    )
    if not result.get("results"):
        raise ProviderError(
            f'Could not find "{city}". Enter a city name, for example Chicago.'
        )
    place = result["results"][0]
    found = {
        "name": ", ".join(
            filter(None, [place["name"], place.get("admin1"), place.get("country")])
        ),
        "lat": place["latitude"],
        "lon": place["longitude"],
    }
    cache.set(key, found, 86400)
    return found


def route_options(origin, destination):
    base = os.getenv("ROUTING_URL", "https://router.project-osrm.org/route/v1/driving")

    def get(points, alternatives="false"):
        coords = ";".join(f"{p[0]},{p[1]}" for p in points)
        data = fetch(
            f"{base}/{coords}",
            {
                "alternatives": alternatives,
                "overview": "full",
                "geometries": "geojson",
                "annotations": "duration,distance",
                "steps": "false",
            },
        )
        if data.get("code") != "Ok":
            raise ProviderError(
                "No connected road route was found between these cities."
            )
        return data["routes"]

    a, b = (origin["lon"], origin["lat"]), (destination["lon"], destination["lat"])
    if math.dist(a, b) < 0.01:
        raise ProviderError("Choose different origin and destination cities.")
    routes = get([a, b], "3")
    # OSRM does not guarantee three natural alternatives. Ask the routing API
    # for real road routes through lateral waypoints when needed.
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy)
    for offset in [0.15, -0.15, 0.3, -0.3]:
        if len(routes) >= 3:
            break
        via = (
            (a[0] + b[0]) / 2 - dy / norm * norm * offset,
            (a[1] + b[1]) / 2 + dx / norm * norm * offset,
        )
        try:
            candidate = get([a, via, b])[0]
        except ProviderError:
            continue
        # Do not present a duplicate road path as an alternative.
        if all(
            candidate["geometry"]["coordinates"] != r["geometry"]["coordinates"]
            and abs(candidate["distance"] - r["distance"]) > 100
            for r in routes
        ):
            candidate["via"] = True
            routes.append(candidate)
    if len(routes) < 3:
        raise ProviderError(
            "The routing service could not find three distinct routes here. Try cities farther apart."
        )
    return routes[:3]


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    v = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(v)))


def sample_route(route, spacing):
    coords = route["geometry"]["coordinates"]
    lengths = [haversine(a, b) for a, b in zip(coords, coords[1:])]
    total = sum(lengths)
    if total == 0:
        raise ProviderError("The routing service returned an empty road path.")
    scale = route["distance"] / total
    lengths = [x * scale for x in lengths]
    durations = [v for leg in route["legs"] for v in leg["annotation"]["duration"]]
    if len(durations) != len(lengths):
        raise ProviderError(
            "The routing service did not return usable segment travel times."
        )
    duration_scale = route["duration"] / sum(durations) if sum(durations) else 1
    durations = [x * duration_scale for x in durations]
    targets = [i * spacing for i in range(math.ceil(route["distance"] / spacing))] + [
        route["distance"]
    ]
    checkpoints, j, dist, seconds = [], 0, 0.0, 0.0
    for target in targets:
        while j < len(lengths) - 1 and dist + lengths[j] < target:
            dist += lengths[j]
            seconds += durations[j]
            j += 1
        f = min(1, max(0, (target - dist) / lengths[j])) if lengths[j] else 0
        a, b = coords[j], coords[j + 1]
        checkpoints.append(
            {
                "lon": a[0] + (b[0] - a[0]) * f,
                "lat": a[1] + (b[1] - a[1]) * f,
                "mile": target / 1609.344,
                "elapsed": seconds + durations[j] * f,
            }
        )
    return checkpoints


def weather(points):
    unique = list(
        dict.fromkeys((round(p["lat"], 4), round(p["lon"], 4)) for p in points)
    )
    result = {}
    missing = []
    for p in unique:
        value = cache.get(f"weather:{p[0]}:{p[1]}")
        if value is None:
            missing.append(p)
        else:
            result[p] = value

    def batch(chunk):
        data = fetch(
            os.getenv("WEATHER_URL", "https://api.open-meteo.com/v1/forecast"),
            {
                "latitude": ",".join(str(p[0]) for p in chunk),
                "longitude": ",".join(str(p[1]) for p in chunk),
                "hourly": "wind_speed_10m,rain,showers,snowfall",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timeformat": "unixtime",
                "timezone": "GMT",
                "forecast_days": 7,
            },
        )
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(chunk):
            raise ProviderError(
                "Incomplete weather response. No recommendation was made."
            )
        for d in data:
            d["hourly"]["snow_unit"] = d["hourly_units"]["snowfall"]
        return list(zip(chunk, [d["hourly"] for d in data]))

    chunks = [missing[i : i + 30] for i in range(0, len(missing), 30)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for batch_result in pool.map(batch, chunks):
            for p, hourly in batch_result:
                cache.set(f"weather:{p[0]}:{p[1]}", hourly, 900)
                result[p] = hourly
    return result


def weather_at(hourly, timestamp):
    import bisect

    # Rain/snow are preceding-hour sums: choose the hour ending after arrival.
    i = bisect.bisect_left(hourly["time"], timestamp)
    if i >= len(hourly["time"]) or timestamp < hourly["time"][0]:
        raise ProviderError(
            "This trip extends beyond the available forecast. Choose an earlier departure or shorter trip."
        )
    values = [hourly[k][i] for k in ["wind_speed_10m", "rain", "showers", "snowfall"]]
    if any(v is None or not math.isfinite(v) for v in values):
        raise ProviderError(
            "Weather is missing for part of this trip. No recommendation was made."
        )
    wind, rain, showers, snow = values
    unit = hourly["snow_unit"]
    if unit not in ["inch", "cm"]:
        raise ProviderError("The weather provider returned unsupported snowfall units.")
    return {
        "wind": wind,
        "rain": rain + showers,
        "snow": snow / 2.54 if unit == "cm" else snow,
    }
