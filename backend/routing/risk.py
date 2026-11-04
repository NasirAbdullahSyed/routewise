"""Pure risk and ranking rules; never round before applying thresholds."""

LABELS = ["Low", "Moderate", "High", "Severe", "No Travel"]


def classify(wind, rain, snow, load):
    wind_risk = (
        4
        if wind >= 55
        else 3 if wind >= 45 else 2 if wind >= 35 else 1 if wind >= 25 else 0
    )
    rain_risk = (
        4
        if rain > 1
        else 3 if rain >= 0.5 else 2 if rain >= 0.25 else 1 if rain >= 0.1 else 0
    )
    snow_risk = (
        4
        if snow > 3
        else 3 if snow >= 2 else 2 if snow >= 1 else 1 if snow >= 0.5 else 0
    )
    if wind >= 45 and load > 30000:
        wind_risk = 4
    elif wind >= 35 and load > 40000:
        wind_risk = max(wind_risk, 3)
    return max(wind_risk, rain_risk, snow_risk)


def summarize(checkpoints, miles, seconds):
    # Each interval takes the worse of its endpoint samples. This includes the
    # destination without counting a full sampling interval beyond the trip.
    exposure = [0.0] * 5
    for a, b in zip(checkpoints, checkpoints[1:]):
        exposure[max(a["risk"], b["risk"])] += b["mile"] - a["mile"]
    return {
        "miles": miles,
        "seconds": seconds,
        "risk_miles": exposure,
        "average_risk": (
            sum(i * m for i, m in enumerate(exposure)) / miles if miles else 0
        ),
        "blocked": any(c["risk"] == 4 for c in checkpoints),
        "max_risk": max(c["risk"] for c in checkpoints),
    }


def rank_key(route):
    s = route["summary"]
    # No Travel is a hard exclusion, then the exact four ordered preferences.
    return (
        s["blocked"],
        round(s["risk_miles"][3], 6),
        round(s["risk_miles"][2], 6),
        round(s["average_risk"], 6),
        s["seconds"],
    )
