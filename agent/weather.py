"""Daily forecast for Tbilisi via Open-Meteo (free, keyless)."""

import json
import urllib.parse
import urllib.request

LAT, LON = 41.7151, 44.8271
CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def forecast(date_iso):
    params = urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "Asia/Tbilisi",
        "start_date": date_iso, "end_date": date_iso,
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{params}", timeout=10) as r:
        daily = json.load(r)["daily"]
    tmax, tmin = daily["temperature_2m_max"][0], daily["temperature_2m_min"][0]
    rain = daily["precipitation_probability_max"][0]
    sky = CODES.get(daily["weather_code"][0], "mixed")
    return {
        "tmax": tmax, "tmin": tmin, "rain_prob": rain, "sky": sky,
        "line": f"{sky.capitalize()}, {round(tmin)}–{round(tmax)}°C, {rain}% chance of rain",
    }
