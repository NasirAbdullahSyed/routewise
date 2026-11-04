"""A bounded geographic grid covering roads and a one-cell lateral buffer."""

import math
from .providers import haversine


def corridor_cells(routes, max_cells=240):
    coordinates = [r["geometry"]["coordinates"] for r in routes]
    all_latitudes = [p[1] for route in coordinates for p in route]
    if not all_latitudes:
        raise ValueError("Cannot create a corridor for an empty route.")
    latitude = (min(all_latitudes) + max(all_latitudes)) / 2
    cosine = max(0.1, math.cos(math.radians(latitude)))
    cell_miles = 10.0
    # Coarsen resolution rather than truncate the end of a long trip.
    while True:
        meters = cell_miles * 1609.344
        lat_step = math.degrees(meters / 6371000)
        lon_step = lat_step / cosine
        cells = set()
        for route in coordinates:
            for a, b in zip(route, route[1:]):
                # Distance-based subdivision also covers sparsely digitized roads.
                count = max(1, math.ceil(haversine(a, b) / (meters / 2)))
                for n in range(count + 1):
                    f = n / count
                    lon = a[0] + (b[0] - a[0]) * f
                    lat = a[1] + (b[1] - a[1]) * f
                    x, y = math.floor(lon / lon_step), math.floor(lat / lat_step)
                    for dx in [-1, 0, 1]:
                        for dy in [-1, 0, 1]:
                            cells.add((x + dx, y + dy))
        if len(cells) <= max_cells:
            break
        cell_miles *= 1.5
    return [
        {
            "lat": (y + 0.5) * lat_step,
            "lon": (x + 0.5) * lon_step,
            "bounds": [
                [y * lat_step, x * lon_step],
                [(y + 1) * lat_step, (x + 1) * lon_step],
            ],
            "cell_miles": cell_miles,
        }
        for x, y in sorted(cells)
    ]
