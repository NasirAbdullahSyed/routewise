import React, { memo, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  MapContainer,
  TileLayer,
  Polyline,
  CircleMarker,
  Rectangle,
  Pane,
  Popup,
  ZoomControl,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { ArrowUpDown, LoaderCircle, AlertTriangle, Check } from "lucide-react";
import "leaflet/dist/leaflet.css";
import "./style.css";
import LocationInput from "./LocationInput";

const colors = ["#2f8a5b", "#d1a11b", "#e2782a", "#cc3a33", "#6d2b6e"];
const labels = ["Low", "Moderate", "High", "Severe", "No Travel"];
const ACCENT = "#0b6e4f";
const OTHER_ROUTE = "#8a96a8";

const fmt = (n, d = 0) =>
  n.toLocaleString(undefined, { maximumFractionDigits: d });
const duration = (seconds) => {
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};
const time = (value) =>
  new Date(value).toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
const localInput = () => {
  const d = new Date(Date.now() + 3600000);
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const shortName = (name) => name.split(",").slice(0, 2).join(",");

function Risk({ level }) {
  return (
    <span className="risk" style={{ "--risk": colors[level] }}>
      <i aria-hidden="true" />
      {labels[level]}
    </span>
  );
}

function Fit({ plan }) {
  const map = useMap();
  useEffect(() => {
    if (!plan) return;
    const fit = () => {
      const forecast = map
        .getContainer()
        .parentElement?.querySelector(".forecast");
      const bottomPadding = (forecast?.offsetHeight || 150) + 64;
      map.fitBounds(
        L.latLngBounds(
          plan.routes.flatMap((r) =>
            r.coordinates.map(([lon, lat]) => [lat, lon]),
          ),
        ),
        {
          paddingTopLeft: [30, 30],
          paddingBottomRight: [30, bottomPadding],
          animate: false,
        },
      );
    };
    fit();
    map.on("resize", fit);
    return () => map.off("resize", fit);
  }, [plan, map]);
  return null;
}

const ForecastCell = memo(function ForecastCell({ point, risk }) {
  return (
    <Rectangle
      bounds={point.bounds}
      interactive={false}
      pathOptions={{ stroke: false, fillColor: colors[risk], fillOpacity: 0.3 }}
    />
  );
});

function Heat({ plan, hour, visible }) {
  return (
    <Pane name="weather" style={{ zIndex: 350, pointerEvents: "none" }}>
      {visible &&
        plan?.corridor.map((p, i) => (
          <ForecastCell key={i} point={p} risk={p.forecast[hour].risk} />
        ))}
    </Pane>
  );
}

function useAccessibleLayer(ref, label) {
  useEffect(() => {
    const layer = ref.current;
    const element = layer?.getElement();
    if (!element) return;
    element.setAttribute("role", "button");
    element.setAttribute("tabindex", "0");
    element.setAttribute("aria-label", label);
    const open = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        layer.fire("click");
        layer.openPopup();
      }
    };
    element.addEventListener("keydown", open);
    return () => element.removeEventListener("keydown", open);
  }, [ref, label]);
}

function Conditions({ p }) {
  return (
    <span className="conditions">
      Wind {fmt(p.wind, 1)} mph, rain {fmt(p.rain, 2)} in/hr, snow{" "}
      {fmt(p.snow, 2)} in/hr
    </span>
  );
}

const CheckpointMarker = memo(function CheckpointMarker({
  p,
  index,
  route,
  selected,
}) {
  const ref = useRef(null);
  useAccessibleLayer(
    ref,
    `${route.name} checkpoint ${index + 1}, ${labels[p.risk]}, mile ${fmt(p.mile, 1)}`,
  );
  return (
    <CircleMarker
      ref={ref}
      center={[p.lat, p.lon]}
      radius={selected ? 5.5 : 3.5}
      pathOptions={{
        color: "#fff",
        weight: selected ? 2 : 1,
        fillColor: colors[p.risk],
        fillOpacity: selected ? 1 : 0.8,
      }}
    >
      <Popup>
        <div className="popup">
          <strong>
            {route.name}, mile {fmt(p.mile, 1)}
          </strong>
          <p>Arrives {time(p.eta)}</p>
          <Risk level={p.risk} />
          <p>
            <Conditions p={p} />
          </p>
        </div>
      </Popup>
    </CircleMarker>
  );
});

const RouteLine = memo(function RouteLine({ route, selected, onSelect }) {
  const ref = useRef(null);
  useAccessibleLayer(ref, `${route.name} summary`);
  useEffect(() => {
    if (selected) ref.current?.bringToFront();
  }, [selected]);
  return (
    <Polyline
      ref={ref}
      positions={route.coordinates.map(([lon, lat]) => [lat, lon])}
      pathOptions={{
        color: selected ? ACCENT : OTHER_ROUTE,
        weight: selected ? 6 : 4,
        opacity: selected ? 1 : 0.75,
      }}
      eventHandlers={{ click: () => onSelect(route.id) }}
    >
      <Popup>
        <div className="popup">
          <strong>{route.name}</strong>
          <p>
            {duration(route.summary.seconds)}, {fmt(route.summary.miles)} mi
            <br />
            Arrives {time(route.checkpoints.at(-1).eta)}
          </p>
          <Risk level={route.summary.max_risk} />
          <p>
            Severe {fmt(route.summary.risk_miles[3], 1)} mi, high{" "}
            {fmt(route.summary.risk_miles[2], 1)} mi
            <br />
            Average risk {route.summary.average_risk.toFixed(2)}
          </p>
        </div>
      </Popup>
    </Polyline>
  );
});

function TripMap({ plan, selected, hour, heat, checkpoints, onSelect }) {
  return (
    <MapContainer
      center={[40.8, -87.1]}
      zoom={7}
      zoomControl={false}
      zoomSnap={0.25}
      zoomDelta={0.5}
    >
      <ZoomControl position="topright" />
      <TileLayer
        attribution='Tiles &copy; Esri, HERE, Garmin, <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Weather: <a href="https://open-meteo.com/">Open-Meteo</a> (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>) · Places: <a href="https://www.geonames.org/">GeoNames</a>'
        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        maxZoom={16}
      />
      <Fit plan={plan} />
      <Heat plan={plan} hour={hour} visible={heat} />
      {plan?.routes.map((r) => (
        <RouteLine
          key={r.id}
          route={r}
          selected={r.id === selected}
          onSelect={onSelect}
        />
      ))}
      <Pane name="checkpoints" style={{ zIndex: 450 }}>
        {checkpoints &&
          plan?.routes
            .filter((r) => r.id !== selected)
            .concat(plan.routes.filter((r) => r.id === selected))
            .flatMap((r) =>
              r.checkpoints.map((p, i) => (
                <CheckpointMarker
                  key={`${r.id}-${i}`}
                  p={p}
                  index={i}
                  route={r}
                  selected={r.id === selected}
                />
              )),
            )}
      </Pane>
    </MapContainer>
  );
}

function RouteCard({ route, recommended, selected, onSelect }) {
  const s = route.summary;
  return (
    <button
      type="button"
      className="route"
      onClick={() => onSelect(route.id)}
      aria-pressed={selected}
    >
      <span className="route-head">
        <span className="route-name">
          {route.name}
          {route.via && <span className="via">via waypoint</span>}
        </span>
        {recommended && (
          <span className="badge">
            <Check size={12} strokeWidth={3} />
            Recommended
          </span>
        )}
      </span>
      <span className="route-main">
        <b>{duration(s.seconds)}</b>
        <span>{fmt(s.miles)} mi</span>
        <span className="route-worst">
          Worst <Risk level={s.max_risk} />
        </span>
      </span>
      <span
        className="exposure"
        role="img"
        aria-label={s.risk_miles
          .map((m, i) => (m > 0.01 ? `${labels[i]} ${fmt(m, 1)} mi` : null))
          .filter(Boolean)
          .join(", ")}
      >
        {s.risk_miles.map(
          (m, i) =>
            m > 0.01 && (
              <span
                key={i}
                style={{ flexGrow: m, background: colors[i] }}
                title={`${labels[i]}: ${fmt(m, 1)} mi`}
              />
            ),
        )}
      </span>
      <span className="route-stats">
        <span>
          <b>{fmt(s.risk_miles[3], 1)}</b> severe mi
        </span>
        <span>
          <b>{fmt(s.risk_miles[2], 1)}</b> high mi
        </span>
        <span>
          <b>{s.average_risk.toFixed(2)}</b> avg risk
        </span>
      </span>
    </button>
  );
}

function App() {
  const [form, setForm] = useState({
    origin: "Chicago",
    destination: "Indianapolis",
    origin_place: null,
    destination_place: null,
    departure: localInput(),
    load: "30000",
    interval: "25",
  });
  const [plan, setPlan] = useState(null);
  const [selected, setSelected] = useState(null);
  const [hour, setHour] = useState(0);
  const [heat, setHeat] = useState(true);
  const [checkpoints, setCheckpoints] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(true);
  const controller = useRef(null);
  const submittedForm = useRef(null);

  const updateForm = (changes) => {
    setError("");
    setForm((previous) => ({ ...previous, ...changes }));
  };
  const change = (e) => updateForm({ [e.target.name]: e.target.value });
  const swap = () => {
    setError("");
    setForm((previous) => ({
      ...previous,
      origin: previous.destination,
      destination: previous.origin,
      origin_place: previous.destination_place,
      destination_place: previous.origin_place,
    }));
  };
  const editTrip = () => {
    if (submittedForm.current) setForm({ ...submittedForm.current });
    setError("");
    setEditing(true);
  };
  const cancelEdit = () => {
    controller.current?.abort();
    controller.current = null;
    if (submittedForm.current) setForm({ ...submittedForm.current });
    setLoading(false);
    setError("");
    setEditing(false);
  };

  async function calculate(demo = false) {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setLoading(true);
    setError("");
    const values = demo
      ? {
          ...form,
          origin: "Chicago",
          destination: "Indianapolis",
          origin_place: null,
          destination_place: null,
          departure: localInput(),
        }
      : { ...form };
    if (demo) setForm(values);
    try {
      const response = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...values,
          load: Number(values.load),
          interval: Number(values.interval),
          departure: new Date(values.departure).toISOString(),
          demo,
        }),
        signal: c.signal,
      });
      const data = await response.json();
      if (c.signal.aborted || controller.current !== c) return;
      if (!response.ok)
        throw new Error(data.error || "Could not plan this trip.");
      submittedForm.current = { ...values };
      setPlan(data);
      setSelected(data.recommended_id ?? data.routes[0].id);
      setHour(0);
      if (!demo) setEditing(false);
    } catch (e) {
      if (controller.current === c && e.name !== "AbortError")
        setError(
          e.message === "Failed to fetch"
            ? "Can't reach the server. Check that Django is running, then try again."
            : e.message,
        );
    } finally {
      if (controller.current === c) setLoading(false);
    }
  }

  useEffect(() => {
    calculate(true);
    return () => controller.current?.abort();
  }, []);

  const route = plan?.routes.find((r) => r.id === selected);
  const forecastTime = plan
    ? time(new Date(plan.forecast_start).getTime() + hour * 3600000)
    : "";

  return (
    <div className="app">
      <aside className="panel">
        <div className="panel-top">
          <header className="brand">
            <span>Routewise</span>
          </header>

          {editing || !plan ? (
            <form
              className="trip"
              onSubmit={(e) => {
                e.preventDefault();
                calculate(false);
              }}
            >
              <div className="places">
                <LocationInput
                  label="From"
                  name="origin"
                  value={form.origin}
                  selected={form.origin_place}
                  onChange={(value, place) =>
                    updateForm({
                      origin: value,
                      origin_place: place,
                    })
                  }
                />
                <LocationInput
                  label="To"
                  name="destination"
                  value={form.destination}
                  selected={form.destination_place}
                  onChange={(value, place) =>
                    updateForm({
                      destination: value,
                      destination_place: place,
                    })
                  }
                />
                <button
                  type="button"
                  className="swap"
                  onClick={swap}
                  aria-label="Swap origin and destination"
                >
                  <ArrowUpDown size={13} />
                  Swap
                </button>
              </div>
              <label>
                <span>Departure (your time)</span>
                <input
                  name="departure"
                  type="datetime-local"
                  value={form.departure}
                  onChange={change}
                  required
                />
              </label>
              <div className="row">
                <label>
                  <span>Load (lb)</span>
                  <input
                    name="load"
                    type="number"
                    inputMode="numeric"
                    min="0"
                    max="100000"
                    step="1"
                    value={form.load}
                    onChange={change}
                    required
                  />
                </label>
                <label>
                  <span>Check weather every</span>
                  <select
                    name="interval"
                    value={form.interval}
                    onChange={change}
                  >
                    <option value="10">10 miles</option>
                    <option value="25">25 miles</option>
                    <option value="50">50 miles</option>
                  </select>
                </label>
              </div>
              <button className="primary" type="submit" disabled={loading}>
                {loading ? (
                  <>
                    <LoaderCircle size={16} className="spin" />
                    Finding routes…
                  </>
                ) : (
                  "Find routes"
                )}
              </button>
              {plan && !plan.demo && (
                <button type="button" className="link" onClick={cancelEdit}>
                  Cancel
                </button>
              )}
            </form>
          ) : (
            <div className="summary">
              <div>
                <b>
                  {shortName(plan.origin.name)} to{" "}
                  {shortName(plan.destination.name)}
                </b>
                <span>
                  Leaving {time(plan.departure)}, {fmt(plan.load)} lb, every{" "}
                  {plan.interval} mi
                </span>
              </div>
              <button type="button" onClick={editTrip}>
                Edit trip
              </button>
            </div>
          )}
          {editing && plan && (
            <div className="result-context">
              <span>
                Results for {shortName(plan.origin.name)} to{" "}
                {shortName(plan.destination.name)}
              </span>
              <small>
                {time(plan.departure)} · {fmt(plan.load)} lb · every{" "}
                {plan.interval} mi
              </small>
            </div>
          )}
          <details className="route-help">
            <summary>Route limitations</summary>
            <p>Truck restrictions, traffic and rest breaks aren't checked.</p>
          </details>
        </div>

        <div className="panel-scroll">
          {error && (
            <div className="alert" role="alert">
              <AlertTriangle size={16} />
              <span>
                {error}
                {plan && " The previous results are still shown."}
              </span>
            </div>
          )}

          {plan?.demo && (
            <p className="notice">
              Showing sample data. Enter a trip and select Find routes for live
              weather.
            </p>
          )}

          {plan && (
            <section className="block" aria-busy={loading}>
              <div className="block-head">
                <h2>Routes</h2>
                <p>
                  {plan.routes.length} options. Select a route for arrival
                  weather.
                </p>
              </div>
              {plan.recommended_id === null && (
                <div className="alert" role="alert">
                  <AlertTriangle size={16} />
                  <span>
                    No route is recommended. Every option has No Travel
                    conditions.
                  </span>
                </div>
              )}
              <div className="routes">
                {plan.routes.map((r) => (
                  <RouteCard
                    key={r.id}
                    route={r}
                    recommended={r.id === plan.recommended_id}
                    selected={r.id === selected}
                    onSelect={setSelected}
                  />
                ))}
              </div>
              {plan.recommended_id !== null && (
                <details className="route-help">
                  <summary>Why recommended?</summary>
                  <p>
                    Ranks severe miles, high miles, average risk, then time. No
                    Travel routes are excluded.
                  </p>
                </details>
              )}
            </section>
          )}

          {route && (
            <section className="block">
              <div className="block-head">
                <h2>{route.name} checkpoints</h2>
                <p>
                  Weather when you arrive at each point, every {plan.interval}{" "}
                  mi
                </p>
              </div>
              <ol className="checkpoints">
                {route.checkpoints.map((p, i) => (
                  <li key={i}>
                    <span
                      className="dot"
                      style={{ background: colors[p.risk] }}
                      aria-hidden="true"
                    />
                    <span className="cp-main">
                      <span className="cp-top">
                        <b>
                          {i === 0
                            ? "Start"
                            : i === route.checkpoints.length - 1
                              ? "Arrive"
                              : `Mile ${fmt(p.mile)}`}
                        </b>
                        <span>{time(p.eta)}</span>
                      </span>
                      <Conditions p={p} />
                    </span>
                    <Risk level={p.risk} />
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </aside>

      <section className="map" aria-label="Route map">
        <TripMap
          plan={plan}
          selected={selected}
          hour={hour}
          heat={heat}
          checkpoints={checkpoints}
          onSelect={setSelected}
        />
        {loading && (
          <div className="map-loading" role="status">
            <LoaderCircle className="spin" size={16} />
            Checking routes and weather…
          </div>
        )}
        <div className="forecast">
          <div className="forecast-head">
            <label htmlFor="hour">
              Forecast <b>{hour === 0 ? "now" : `+${hour}h`}</b>
              <span>{forecastTime}</span>
            </label>
            <div className="toggles">
              <label>
                <input
                  type="checkbox"
                  checked={heat}
                  onChange={(e) => setHeat(e.target.checked)}
                />
                Weather
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={checkpoints}
                  onChange={(e) => setCheckpoints(e.target.checked)}
                />
                Checkpoints
              </label>
            </div>
          </div>
          <input
            id="hour"
            type="range"
            min="0"
            max="48"
            step="1"
            value={hour}
            onChange={(e) => setHour(+e.target.value)}
            disabled={!plan}
            style={{ "--fill": `${(hour / 48) * 100}%` }}
          />
          <div className="forecast-foot">
            <div className="legend">
              {labels.map((l, i) => (
                <Risk key={l} level={i} />
              ))}
            </div>
            <span>
              {plan && `${fmt(plan.corridor_resolution_miles, 1)} mi cells. `}
              Slider moves the weather layer only.
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
