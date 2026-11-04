import React, { useEffect, useId, useState } from "react";

export default function LocationInput({
  label,
  name,
  value,
  selected,
  onChange,
}) {
  const id = useId();
  const [focused, setFocused] = useState(false);
  const [results, setResults] = useState([]);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState("");
  const query = value.trim();

  useEffect(() => {
    setResults([]);
    setActive(-1);
    setStatus("");
    if (!focused || selected || query.length < 3) return;
    const controller = new AbortController();
    let cancelled = false;
    setStatus("Searching cities…");
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `/api/locations?q=${encodeURIComponent(query)}`,
          {
            signal: controller.signal,
          },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        if (cancelled) return;
        setResults(data.results);
        setStatus(
          data.results.length
            ? ""
            : "No cities found. Try a longer name or add a country.",
        );
      } catch (error) {
        if (!cancelled && error.name !== "AbortError") {
          setStatus("Suggestions unavailable. Keep typing to try again.");
        }
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [focused, query, selected]);

  const open = focused && !selected && query.length >= 3;
  useEffect(() => {
    if (open && active >= 0) {
      document
        .getElementById(`${id}-option-${active}`)
        ?.scrollIntoView({ block: "nearest" });
    }
  }, [open, active, id]);
  const choose = (place) => {
    onChange(place.name, place);
    setFocused(false);
    setResults([]);
    setActive(-1);
  };
  const keyDown = (event) => {
    if (event.key === "Escape") {
      setFocused(false);
      setActive(-1);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setFocused(true);
      if (results.length) {
        setActive((previous) =>
          event.key === "ArrowDown"
            ? (previous + 1) % results.length
            : previous <= 0
              ? results.length - 1
              : previous - 1,
        );
      }
    } else if (event.key === "Enter" && open && results.length) {
      event.preventDefault();
      choose(results[active < 0 ? 0 : active]);
    }
  };

  return (
    <div className="location-field">
      <label htmlFor={id}>
        <span>{label}</span>
      </label>
      <input
        id={id}
        name={name}
        value={value}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open && results.length > 0}
        aria-controls={`${id}-list`}
        aria-activedescendant={
          open && active >= 0 ? `${id}-option-${active}` : undefined
        }
        aria-describedby={open && status ? `${id}-status` : undefined}
        autoComplete="off"
        placeholder="Start typing a city"
        required
        minLength={2}
        maxLength={200}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={keyDown}
        onChange={(event) => {
          setResults([]);
          setActive(-1);
          setFocused(true);
          onChange(event.target.value, null);
        }}
      />
      {open && (
        <div className="location-menu">
          <ul
            id={`${id}-list`}
            role="listbox"
            aria-label={`${label} city suggestions`}
          >
            {results.map((place, index) => (
              <li
                key={place.id}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={active === index}
                onPointerDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(place)}
              >
                <strong>{place.city}</strong>
                <small>{place.region}</small>
              </li>
            ))}
          </ul>
          {status && (
            <p id={`${id}-status`} role="status">
              {status}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
