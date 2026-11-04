import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from django.test import SimpleTestCase
from .risk import classify, summarize, rank_key
from .providers import sample_route, weather_at, ProviderError
from .service import demo_routes


class RiskTests(SimpleTestCase):
    def test_wind_boundaries(self):
        for wind, expected in [
            (24.99, 0),
            (25, 1),
            (34.99, 1),
            (35, 2),
            (44.99, 2),
            (45, 3),
            (54.99, 3),
            (55, 4),
        ]:
            with self.subTest(wind=wind):
                self.assertEqual(classify(wind, 0, 0, 0), expected)

    def test_rain_snow_boundaries(self):
        for rain, expected in [
            (0.099, 0),
            (0.1, 1),
            (0.25, 2),
            (0.5, 3),
            (1, 3),
            (1.001, 4),
        ]:
            self.assertEqual(classify(0, rain, 0, 0), expected)
        for snow, expected in [(0.49, 0), (0.5, 1), (1, 2), (2, 3), (3, 3), (3.001, 4)]:
            self.assertEqual(classify(0, 0, snow, 0), expected)

    def test_strict_load_thresholds(self):
        for wind, load, expected in [
            (45, 30000, 3),
            (45, 30001, 4),
            (35, 40000, 2),
            (35, 40001, 3),
            (55, 0, 4),
            (34.99, 90000, 1),
        ]:
            self.assertEqual(classify(wind, 0, 0, load), expected)

    def test_worst_condition_wins(self):
        self.assertEqual(classify(10, 0.3, 2.5, 0), 3)
        self.assertEqual(classify(55, 0, 0, 0), 4)

    def test_weighted_exposure_and_destination(self):
        s = summarize(
            [{"mile": 0, "risk": 0}, {"mile": 10, "risk": 1}, {"mile": 12, "risk": 3}],
            12,
            100,
        )
        self.assertEqual(s["risk_miles"], [0, 10, 0, 2, 0])
        self.assertAlmostEqual(s["average_risk"], 16 / 12)
        self.assertEqual(sum(s["risk_miles"]), 12)

    def test_recommendation_order(self):
        def r(blocked=False, severe=0, high=0, avg=0, seconds=10):
            return {
                "summary": {
                    "blocked": blocked,
                    "risk_miles": [0, 0, high, severe, 0],
                    "average_risk": avg,
                    "seconds": seconds,
                }
            }

        for better, worse in [
            (r(seconds=99), r(blocked=True)),
            (r(high=100), r(severe=1)),
            (r(avg=2), r(high=1)),
            (r(seconds=99), r(avg=1)),
            (r(seconds=5), r(seconds=10)),
        ]:
            self.assertLess(rank_key(better), rank_key(worse))


class SamplingTests(SimpleTestCase):
    def test_interval_endpoint_and_eta(self):
        route = demo_routes()[0]
        points = sample_route(route, round(25 * 1609.344))
        self.assertEqual(points[0]["elapsed"], 0)
        self.assertAlmostEqual(points[-1]["elapsed"], route["duration"])
        self.assertAlmostEqual(points[-1]["mile"], route["distance"] / 1609.344)
        self.assertTrue(
            all(
                a["mile"] < b["mile"] and a["elapsed"] <= b["elapsed"]
                for a, b in zip(points, points[1:])
            )
        )
        self.assertLessEqual(points[-1]["mile"] - points[-2]["mile"], 25.001)
        self.assertAlmostEqual(points[-1]["lat"], 39.77)

    def test_weather_hour_units_and_missing(self):
        hourly = {
            "time": [0, 3600, 7200],
            "wind_speed_10m": [1, 20, 30],
            "rain": [0, 0.2, 0.3],
            "showers": [0, 0.1, 0.2],
            "snowfall": [0, 1, 2],
            "snow_unit": "inch",
        }
        w = weather_at(hourly, 1)
        self.assertEqual(w["snow"], 1)
        self.assertAlmostEqual(w["rain"], 0.3)
        hourly["snow_unit"] = "cm"
        self.assertAlmostEqual(weather_at(hourly, 3600)["snow"], 1 / 2.54)
        with self.assertRaises(ProviderError):
            weather_at(hourly, 7201)
        hourly["rain"][1] = None
        with self.assertRaises(ProviderError):
            weather_at(hourly, 1)


class APITests(SimpleTestCase):
    def payload(self, **kwargs):
        return {
            "origin": "Chicago",
            "destination": "Indianapolis",
            "departure": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "load": 30000,
            "interval": 25,
            "demo": True,
            **kwargs,
        }

    def test_demo_full_response(self):
        response = self.client.post(
            "/api/plan", json.dumps(self.payload()), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["demo"])
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual(len(data["corridor"][0]["forecast"]), 49)
        self.assertIsNotNone(data["recommended_id"])
        for route in data["routes"]:
            self.assertAlmostEqual(
                sum(route["summary"]["risk_miles"]), route["summary"]["miles"]
            )

    def test_invalid_and_stale_inputs(self):
        for values in [
            {"load": -1},
            {"load": float("nan")},
            {"interval": 15},
            {"departure": "invalid"},
            {"departure": datetime.now().isoformat()},
            {"departure": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()},
            {"origin": ""},
            {"demo": "false"},
        ]:
            response = self.client.post(
                "/api/plan",
                json.dumps(self.payload(**values)),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400, values)
        self.assertEqual(self.client.get("/api/plan").status_code, 405)
        self.assertEqual(
            self.client.post(
                "/api/plan", "{", content_type="application/json"
            ).status_code,
            400,
        )

    @patch("routing.service.geocode", side_effect=ProviderError("Unavailable"))
    def test_provider_error_is_not_fake_success(self, _):
        response = self.client.post(
            "/api/plan",
            json.dumps(self.payload(demo=False)),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("routes", response.json())

    @patch("routing.service.classify", return_value=4)
    def test_all_routes_blocked(self, _):
        response = self.client.post(
            "/api/plan", json.dumps(self.payload()), content_type="application/json"
        )
        self.assertIsNone(response.json()["recommended_id"])


class CorridorTests(SimpleTestCase):
    def cells(self, coords):
        from .corridor import corridor_cells

        return corridor_cells([{"geometry": {"coordinates": coords}}])

    def test_north_south_and_east_west_have_lateral_coverage(self):
        for coords in [[[-87, 40], [-87, 44]], [[-90, 41], [-84, 41]]]:
            cells = self.cells(coords)
            self.assertGreater(len({p["lon"] for p in cells}), 2)
            self.assertGreater(len({p["lat"] for p in cells}), 2)
            for a, b in zip(coords, coords[1:]):
                for n in range(101):
                    lon = a[0] + (b[0] - a[0]) * n / 100
                    lat = a[1] + (b[1] - a[1]) * n / 100
                    self.assertTrue(
                        any(
                            p["bounds"][0][0] <= lat <= p["bounds"][1][0]
                            and p["bounds"][0][1] <= lon <= p["bounds"][1][1]
                            for p in cells
                        )
                    )

    def test_overlap_does_not_add_density(self):
        from .corridor import corridor_cells

        route = {"geometry": {"coordinates": [[-87, 40], [-87, 44]]}}
        self.assertEqual(corridor_cells([route]), corridor_cells([route, route, route]))

    def test_long_sparse_route_remains_bounded_and_reaches_destination(self):
        cells = self.cells([[-120, 37], [-74, 41]])
        self.assertLessEqual(len(cells), 240)
        self.assertGreater(cells[0]["cell_miles"], 10)
        for lon, lat in [[-120, 37], [-74, 41]]:
            self.assertTrue(
                any(
                    p["bounds"][0][0] <= lat <= p["bounds"][1][0]
                    and p["bounds"][0][1] <= lon <= p["bounds"][1][1]
                    for p in cells
                )
            )


class ProviderTests(SimpleTestCase):
    @patch("routing.providers.fetch")
    def test_batch_weather_units_and_cache(self, fetch):
        from django.core.cache import cache
        from .providers import weather

        cache.clear()

        def response(url, params):
            return [
                {
                    "hourly": {
                        "time": [0],
                        "wind_speed_10m": [1],
                        "rain": [0],
                        "showers": [0],
                        "snowfall": [0],
                    },
                    "hourly_units": {"snowfall": "inch"},
                }
                for _ in params["latitude"].split(",")
            ]

        fetch.side_effect = response
        points = [{"lat": i / 10, "lon": 0} for i in range(31)]
        result = weather(points + points)
        self.assertEqual(len(result), 31)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result[(0, 0)]["snow_unit"], "inch")
        weather(points)
        self.assertEqual(fetch.call_count, 2)
        cache.clear()

    @patch("routing.providers.fetch", return_value=[])
    def test_incomplete_batch_is_rejected(self, _):
        from django.core.cache import cache
        from .providers import weather

        cache.clear()
        with self.assertRaises(ProviderError):
            weather([{"lat": 0, "lon": 0}])

    @patch("routing.providers.fetch")
    def test_waypoint_fallback_has_three_distinct_routes(self, fetch):
        from .providers import route_options

        routes = [
            {"distance": n * 1000, "geometry": {"coordinates": [[0, 0], [n, 1]]}}
            for n in [1, 2, 3]
        ]
        fetch.side_effect = [{"code": "Ok", "routes": [r]} for r in routes]
        result = route_options({"lon": 0, "lat": 0}, {"lon": 3, "lat": 1})
        self.assertEqual(len(result), 3)
        self.assertTrue(result[1]["via"])
        self.assertTrue(result[2]["via"])

    @patch("routing.providers.fetch")
    def test_duplicate_waypoints_are_not_accepted(self, fetch):
        from .providers import route_options

        fetch.return_value = {
            "code": "Ok",
            "routes": [
                {"distance": 1000, "geometry": {"coordinates": [[0, 0], [3, 1]]}}
            ],
        }
        with self.assertRaises(ProviderError):
            route_options({"lon": 0, "lat": 0}, {"lon": 3, "lat": 1})


class LocationTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    @patch("routing.providers.fetch")
    def test_search_returns_distinguishable_places_and_caches_results(self, fetch):
        fetch.return_value = {
            "results": [
                {
                    "id": 1,
                    "name": "London",
                    "admin1": "England",
                    "country": "United Kingdom",
                    "latitude": 51.5,
                    "longitude": -0.12,
                },
                {
                    "id": 2,
                    "name": "London",
                    "admin1": "Ontario",
                    "country": "Canada",
                    "latitude": 42.98,
                    "longitude": -81.23,
                },
            ]
        }
        response = self.client.get("/api/locations", {"q": "London"})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(results[1]["name"], "London, Ontario, Canada")
        self.assertEqual(len(results), 2)
        self.client.get("/api/locations", {"q": "London"})
        self.assertEqual(fetch.call_count, 1)

    @patch("routing.providers.fetch", return_value={})
    def test_empty_search_and_query_validation(self, fetch):
        self.assertEqual(
            self.client.get("/api/locations", {"q": "zzzyyyxxx"}).json(),
            {"results": []},
        )
        fetch.reset_mock()
        self.assertEqual(
            self.client.get("/api/locations", {"q": "Lo"}).json(), {"results": []}
        )
        self.assertEqual(
            self.client.get("/api/locations", {"q": "L" * 121}).status_code, 400
        )
        self.assertEqual(self.client.post("/api/locations").status_code, 405)
        fetch.assert_not_called()

    @patch("routing.views.search_locations", side_effect=ProviderError("Unavailable"))
    def test_search_failure_is_reported(self, _):
        self.assertEqual(
            self.client.get("/api/locations", {"q": "London"}).status_code, 502
        )

    @patch("routing.providers.fetch")
    def test_selected_place_is_not_replaced_by_first_city_match(self, fetch):
        from .providers import geocode

        selected = {"name": "London, Ontario, Canada", "lat": 42.98, "lon": -81.23}
        self.assertEqual(geocode(selected["name"], selected), selected)
        fetch.assert_not_called()
        for invalid in [
            {**selected, "lat": float("nan")},
            {**selected, "lon": 181},
            {**selected, "name": "Different city"},
            {},
        ]:
            with self.assertRaises(ValueError):
                geocode(selected["name"], invalid)

    @patch(
        "routing.service.route_options",
        side_effect=ProviderError("Stop after resolution"),
    )
    def test_planning_receives_the_selected_coordinates(self, route_options):
        origin = {"name": "London, Ontario, Canada", "lat": 42.98, "lon": -81.23}
        destination = {"name": "Toronto, Ontario, Canada", "lat": 43.65, "lon": -79.38}
        payload = {
            "origin": origin["name"],
            "destination": destination["name"],
            "origin_place": origin,
            "destination_place": destination,
            "departure": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "load": 30000,
            "interval": 25,
            "demo": False,
        }
        response = self.client.post(
            "/api/plan", json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 502)
        route_options.assert_called_once_with(origin, destination)
