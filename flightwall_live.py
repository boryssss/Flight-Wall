import argparse
import json
import math
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
import pygame
import requests
from bs4 import BeautifulSoup


# ============================================================
# FLIGHTWALL LIVE - 128x64
# ============================================================
# Default cycle:
#   60s aircraft -> 10s POZ arrivals -> 10s POZ departures
#   + 12s full-height 40NM radar/weather overlay every 3 minutes
#   + airline-colour dots; focused aircraft blinks and shows callsign
#   + METAR weather icon next to temperature
#   + radar stays until every visible aircraft has blinked once
#   + 1px Poznan-Lawica mosaic frame around the entire radar screen
#   + focused aircraft uses 4x4 X-style blinking marker
#   + --matrix output for a real 128x64 HUB75 panel
#   + --matrix-test hardware colour/geometry test
#
# Keys:
#   A = aircraft
#   R = arrivals
#   D = departures
#   SPACE = next screen
#   N = next aircraft
#   G = LED grid on/off
#   M = radar/weather screen
#   F = force refresh
#   ESC = exit
#
# Live sources:
#   ADSB.lol -> nearby aircraft
#   HexDB    -> route / aircraft / airport enrichment
#   poznanairport.pl -> POZ arrivals/departures
#   aviationweather.gov -> EPPO METAR weather
# ============================================================


VERSION = "0.25"

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOGO_DIR = BASE_DIR / "logos"
CACHE_DIR = BASE_DIR / "cache"
MISSING_LOGOS_PATH = BASE_DIR / "missing_logos.json"

IGNORED_REGISTRATIONS = {
    "TLXU05",
    "TXLU05",
}

IGNORED_CALLSIGNS = {
    "TLXU05",
    "TXLU05",
}

IGNORED_AIRLINE_ICAO = {
    "TXL",
}

MATRIX_W = 128
MATRIX_H = 64

BG = (4, 4, 6)
LED_OFF = (11, 11, 14)
WHITE = (240, 240, 240)
YELLOW = (255, 215, 40)
BLUE = (70, 150, 255)
RED = (255, 70, 70)
CYAN = (70, 220, 255)
GREEN = (80, 230, 120)
GRAY = (145, 145, 155)
ORANGE = (255, 160, 60)

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

FONT_5X7 = {
    "A": ["01110","10001","10001","11111","10001","10001","10001"],
    "B": ["11110","10001","10001","11110","10001","10001","11110"],
    "C": ["01111","10000","10000","10000","10000","10000","01111"],
    "D": ["11110","10001","10001","10001","10001","10001","11110"],
    "E": ["11111","10000","10000","11110","10000","10000","11111"],
    "F": ["11111","10000","10000","11110","10000","10000","10000"],
    "G": ["01111","10000","10000","10111","10001","10001","01111"],
    "H": ["10001","10001","10001","11111","10001","10001","10001"],
    "I": ["11111","00100","00100","00100","00100","00100","11111"],
    "J": ["00111","00010","00010","00010","10010","10010","01100"],
    "K": ["10001","10010","10100","11000","10100","10010","10001"],
    "L": ["10000","10000","10000","10000","10000","10000","11111"],
    "M": ["10001","11011","10101","10101","10001","10001","10001"],
    "N": ["10001","11001","10101","10011","10001","10001","10001"],
    "O": ["01110","10001","10001","10001","10001","10001","01110"],
    "P": ["11110","10001","10001","11110","10000","10000","10000"],
    "Q": ["01110","10001","10001","10001","10101","10010","01101"],
    "R": ["11110","10001","10001","11110","10100","10010","10001"],
    "S": ["01111","10000","10000","01110","00001","00001","11110"],
    "T": ["11111","00100","00100","00100","00100","00100","00100"],
    "U": ["10001","10001","10001","10001","10001","10001","01110"],
    "V": ["10001","10001","10001","10001","10001","01010","00100"],
    "W": ["10001","10001","10001","10101","10101","10101","01010"],
    "X": ["10001","10001","01010","00100","01010","10001","10001"],
    "Y": ["10001","10001","01010","00100","00100","00100","00100"],
    "Z": ["11111","00001","00010","00100","01000","10000","11111"],

    "0": ["01110","10001","10011","10101","11001","10001","01110"],
    "1": ["00100","01100","00100","00100","00100","00100","01110"],
    "2": ["01110","10001","00001","00010","00100","01000","11111"],
    "3": ["11110","00001","00001","01110","00001","00001","11110"],
    "4": ["00010","00110","01010","10010","11111","00010","00010"],
    "5": ["11111","10000","10000","11110","00001","00001","11110"],
    "6": ["01110","10000","10000","11110","10001","10001","01110"],
    "7": ["11111","00001","00010","00100","01000","01000","01000"],
    "8": ["01110","10001","10001","01110","10001","10001","01110"],
    "9": ["01110","10001","10001","01111","00001","00001","01110"],

    "-": ["00000","00000","00000","11111","00000","00000","00000"],
    ">": ["10000","01000","00100","00010","00100","01000","10000"],
    ".": ["00000","00000","00000","00000","00000","00110","00110"],
    "/": ["00001","00010","00010","00100","01000","01000","10000"],
    ":": ["00000","00110","00110","00000","00110","00110","00000"],
    "?": ["01110","10001","00001","00010","00100","00000","00100"],
    "°": ["01100","10010","10010","01100","00000","00000","00000"],
    " ": ["00000","00000","00000","00000","00000","00000","00000"],
}


DEFAULT_CONFIG = {
    "display": {
        "scale": 7,
        "fps": 60,
        "show_grid": True
    },
    "matrix": {
        "rows": 64,
        "cols": 128,
        "chain_length": 1,
        "parallel": 1,
        "hardware_mapping": "regular",
        "gpio_slowdown": 4,
        "brightness": 35,
        "fps": 20
    },
    "location": {
        "name": "POZ",
        "lat": 52.416123,
        "lon": 16.637221,
        "radius_nm": 40
    },
    "refresh": {
        "adsb_seconds": 10,
        "airport_seconds": 60,
        "hexdb_timeout_seconds": 6,
        "http_timeout_seconds": 12
    },
    "screens": {
        "aircraft_seconds": 60,
        "arrivals_seconds": 10,
        "departures_seconds": 10
    },
    "aircraft": {
        "max_candidates": 12,
        "route_enrich_top": 6
    },
    "radar": {
        "show_every_seconds": 180,
        "screen_seconds": 12,
        "range_nm": 40,
        "focus_seconds": 3,
        "blink_ms": 350,
        "home_lat": 52.41612629043059,
        "home_lon": 16.63722532907901,
        "airport_lat": 52.421,
        "airport_lon": 16.8263
    },
    "weather": {
        "refresh_seconds": 300,
        "station": "EPPO"
    }
}
def draw_arrow_right(buf, x, y, color):
    pixels = [
        (0,2),(1,2),(2,2),(3,2),(4,2),(5,2),
        (3,0),(4,1),
        (4,3),(3,4),
    ]

    for px, py in pixels:
        set_pixel(buf, x + px, y + py, color)

def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return DEFAULT_CONFIG

    try:
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return deep_merge(DEFAULT_CONFIG, user)
    except Exception:
        return DEFAULT_CONFIG


CONFIG = load_config()
SCALE = int(CONFIG["display"]["scale"])
FPS = int(CONFIG["display"]["fps"])
WINDOW_W = MATRIX_W * SCALE
WINDOW_H = MATRIX_H * SCALE

HTTP_TIMEOUT = int(CONFIG["refresh"]["http_timeout_seconds"])
HEXDB_TIMEOUT = int(CONFIG["refresh"]["hexdb_timeout_seconds"])

HOME_LAT = float(CONFIG["radar"]["home_lat"])
HOME_LON = float(CONFIG["radar"]["home_lon"])
POZ_LAT = float(CONFIG["radar"]["airport_lat"])
POZ_LON = float(CONFIG["radar"]["airport_lon"])

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "FlightWall-DIY/0.1 (+personal hobby project)"
})


def safe_json_load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_json_save(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    tmp.replace(path)


HEXDB_CACHE_PATH = CACHE_DIR / "hexdb_cache.json"
AIRPORT_CACHE_PATH = CACHE_DIR / "airport_board_cache.json"
AIRPORT_DEBUG_PATH = BASE_DIR / "airport_debug.txt"
DEPARTURES_RAW_PATH = CACHE_DIR / "poz_departures_raw.html"
ARRIVALS_RAW_PATH = CACHE_DIR / "poz_arrivals_raw.html"
POZ_ROUTE_CACHE_PATH = CACHE_DIR / "poz_route_fallback.json"

# Full-day POZ board index used only when HexDB has no route.
# It is rebuilt whenever the official airport board refreshes.
POZ_ROUTE_INDEX = safe_json_load(
    POZ_ROUTE_CACHE_PATH,
    {"by_flight": {}, "by_suffix": {}}
)

hexdb_cache = safe_json_load(
    HEXDB_CACHE_PATH,
    {"aircraft": {}, "route": {}, "airport": {}}
)

# Avoid counting the same aircraft every ADS-B refresh.
MISSING_LOGO_SEEN_THIS_RUN = set()


# ============================================================
# HELPERS
# ============================================================

def clean_callsign(value):
    return (value or "").strip().upper()


def normalize_flight_number(value):
    return re.sub(r"\s+", "", (value or "").upper())


def airline_icao_from_callsign(callsign):
    m = re.match(r"^([A-Z]{3})", clean_callsign(callsign))
    return m.group(1) if m else ""


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def fmt_alt(v):
    if v is None or v == "":
        return "-----FT"
    if isinstance(v, str) and v.lower() == "ground":
        return "GROUND"
    try:
        return f"{int(float(v))}FT"
    except Exception:
        return "-----FT"


def fmt_speed(v):
    try:
        return f"{int(round(float(v)))}KT"
    except Exception:
        return "---KT"


def fmt_distance(km):
    try:
        return f"{float(km):.1f}KM"
    except Exception:
        return "--.-KM"


def fmt_heading(v):
    try:
        return f"{int(round(float(v))) % 360:03d}"
    except Exception:
        return "---"


def log_missing_logo(icao, callsign=""):
    """
    Record a missing airline logo.

    One ICAO/callsign pair is counted once per program run, so a plane
    refreshed every 10 seconds does not inflate the counter.
    """
    icao = (icao or "").strip().upper()
    callsign = clean_callsign(callsign)

    if not icao:
        return

    # Logo exists -> nothing is missing.
    if (LOGO_DIR / f"{icao}.png").exists():
        return

    seen_key = (icao, callsign or "?")
    if seen_key in MISSING_LOGO_SEEN_THIS_RUN:
        return

    MISSING_LOGO_SEEN_THIS_RUN.add(seen_key)

    data = safe_json_load(MISSING_LOGOS_PATH, {})
    now = datetime.now(WARSAW_TZ).strftime("%Y-%m-%d %H:%M:%S")

    entry = data.setdefault(icao, {
        "first_seen": now,
        "last_seen": now,
        "count": 0,
        "example_callsigns": []
    })

    entry["last_seen"] = now
    entry["count"] = int(entry.get("count", 0)) + 1

    if callsign:
        examples = entry.setdefault("example_callsigns", [])
        if callsign not in examples:
            examples.append(callsign)
            del examples[5:]

    safe_json_save(MISSING_LOGOS_PATH, data)

    print(
        f"[MISSING LOGO] {icao}"
        + (f" ({callsign})" if callsign else ""),
        flush=True
    )


# ============================================================
# HEXDB
# ============================================================

def hexdb_get(kind, key):
    key = (key or "").strip().upper()
    if not key:
        return None

    bucket = hexdb_cache.setdefault(kind, {})

    # Reuse only successful cached responses.
    # A temporary 404/network failure must not lock a callsign at ??? -> ???.
    if key in bucket and bucket[key] is not None:
        return bucket[key]

    # Remove stale negative cache entries written by older versions.
    if key in bucket and bucket[key] is None:
        bucket.pop(key, None)

    if kind == "aircraft":
        url = f"https://hexdb.io/api/v1/aircraft/{key}"
    elif kind == "route":
        url = f"https://hexdb.io/api/v1/route/icao/{key}"
    elif kind == "airport":
        url = f"https://hexdb.io/api/v1/airport/icao/{key}"
    else:
        return None

    try:
        r = SESSION.get(url, timeout=HEXDB_TIMEOUT)
        if r.status_code != 200:
            print(
                f"[HEXDB] {kind} {key}: HTTP {r.status_code}",
                flush=True
            )
            return None

        data = r.json()
        if isinstance(data, dict) and str(data.get("status")) == "404":
            print(f"[HEXDB] {kind} {key}: not found", flush=True)
            return None

        # Cache only successful responses.
        bucket[key] = data
        safe_json_save(HEXDB_CACHE_PATH, hexdb_cache)
        return data
    except Exception as exc:
        print(
            f"[HEXDB] {kind} {key}: {type(exc).__name__}: {exc}",
            flush=True
        )
        return None


def route_to_iata(route_string):
    if not route_string:
        return None, None

    parts = re.split(r"[-–—\s]+", route_string.strip().upper())
    if len(parts) < 2:
        return None, None

    origin_icao = parts[0]
    dest_icao = parts[-1]

    origin_data = hexdb_get("airport", origin_icao)
    dest_data = hexdb_get("airport", dest_icao)

    origin = (
        origin_data.get("iata")
        if isinstance(origin_data, dict)
        else None
    ) or origin_icao

    dest = (
        dest_data.get("iata")
        if isinstance(dest_data, dict)
        else None
    ) or dest_icao

    return origin, dest


# ============================================================
# ADSB.LOL
# ============================================================

def fetch_nearby_aircraft():
    lat = float(CONFIG["location"]["lat"])
    lon = float(CONFIG["location"]["lon"])
    radius_nm = float(CONFIG["location"]["radius_nm"])

    url = f"https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}"

    r = SESSION.get(url, timeout=HTTP_TIMEOUT)

    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After")
        try:
            retry_after = int(retry_after)
        except Exception:
            retry_after = 60

        raise RuntimeError(
            f"ADSB_RATE_LIMIT:{retry_after}"
        )

    r.raise_for_status()
    payload = r.json()
    raw_aircraft = payload.get("ac", [])

    planes = []

    for raw in raw_aircraft:
        callsign = clean_callsign(raw.get("flight"))
        plat = raw.get("lat")
        plon = raw.get("lon")
        registration = (raw.get("r") or "").strip().upper()

        if registration in IGNORED_REGISTRATIONS:
            print(
                f"[ADSB IGNORE] {registration} ({callsign or 'NO CALLSIGN'})",
                flush=True
            )
            continue

        if not callsign or plat is None or plon is None:
            continue

        try:
            distance_km = haversine_km(
                lat, lon, float(plat), float(plon)
            )
        except Exception:
            continue

        raw_airline = (raw.get("ownOp") or "").strip()

        # Completely ignore unwanted ADS-B targets.
        inferred_icao = airline_icao_from_callsign(callsign)

        if should_exclude_aircraft(
            registration,
            callsign,
            raw_airline,
            inferred_icao
        ):
            print(
                f"[ADSB FILTER] skipped "
                f"callsign={callsign} reg={registration or '-'} "
                f"airline={raw_airline or '-'}",
                flush=True
            )
            continue

        plane = {
            "callsign": callsign,
            "hex": (raw.get("hex") or "").strip().upper(),
            "lat": plat,
            "lon": plon,
            "distance_km": distance_km,
            "alt": raw.get("alt_baro"),
            "speed": raw.get("gs"),
            "heading": raw.get("track"),
            "vertical_speed": (
                raw.get("baro_rate")
                if raw.get("baro_rate") is not None
                else raw.get("geom_rate")
            ),
            "aircraft": raw.get("t") or "",
            "registration": registration,
            "airline": raw_airline,
            "icao": inferred_icao,
            "origin": None,
            "destination": None,
            "route": None
        }

        planes.append(plane)

    planes.sort(key=lambda x: x["distance_km"])
    planes = planes[:int(CONFIG["aircraft"]["max_candidates"])]

    enrich_count = min(
        len(planes),
        int(CONFIG["aircraft"]["route_enrich_top"])
    )

    for plane in planes[:enrich_count]:
        callsign = plane["callsign"]

        # Route lookup
        route_data = hexdb_get("route", callsign)
        if isinstance(route_data, dict):
            plane["route"] = route_data.get("route")
            origin, dest = route_to_iata(plane["route"])
            plane["origin"] = origin
            plane["destination"] = dest

        # HexDB always has priority. Only when it did not give us a usable
        # route do we check today's official Poznan Airport board.
        if not plane["origin"] or not plane["destination"]:
            poz_route = route_from_poz_board(
                callsign,
                plane.get("vertical_speed")
            )

            if poz_route:
                plane["origin"] = poz_route["origin"]
                plane["destination"] = poz_route["destination"]
                plane["route"] = (
                    f"{plane['origin']}-{plane['destination']}"
                )

                print(
                    f"[ROUTE FALLBACK] {callsign}: "
                    f"{poz_route.get('direction')} "
                    f"{poz_route.get('flight')} -> "
                    f"{plane['origin']}-{plane['destination']} "
                    f"({poz_route.get('match')}, "
                    f"vs={plane.get('vertical_speed')}, "
                    f"dt={poz_route.get('time_distance_min', '-')}m)",
                    flush=True
                )
            else:
                print(
                    f"[ROUTE] {callsign}: "
                    "HexDB empty and no POZ-board match",
                    flush=True
                )
        else:
            print(
                f"[ROUTE HEXDB] {callsign}: "
                f"{plane['origin']}-{plane['destination']}",
                flush=True
            )

        # Aircraft lookup only when ADSB.lol is missing useful fields
        if plane["hex"] and (
            not plane["aircraft"]
            or not plane["registration"]
            or not plane["airline"]
            or not plane["icao"]
        ):
            ac_data = hexdb_get("aircraft", plane["hex"])
            if isinstance(ac_data, dict):
                plane["aircraft"] = (
                    plane["aircraft"]
                    or ac_data.get("ICAOTypeCode")
                    or ""
                )
                plane["registration"] = (
                    plane["registration"]
                    or ac_data.get("Registration")
                    or ""
                )
                plane["airline"] = (
                    plane["airline"]
                    or ac_data.get("RegisteredOwners")
                    or ""
                )
                # Branding follows the live callsign first. This prevents a
                # wet-lease/ACMI/owner record from replacing e.g. SAS with the
                # registered operator returned by HexDB.
                callsign_icao = airline_icao_from_callsign(callsign)
                plane["icao"] = (
                    callsign_icao
                    or plane["icao"]
                    or ac_data.get("OperatorFlagCode")
                    or ""
                )

    # Re-check exclusions after enrichment as airline data may have
    # appeared only after HexDB lookup.
    filtered_planes = []
    for plane in planes:
        if should_exclude_aircraft(
            plane.get("registration", ""),
            plane.get("callsign", ""),
            plane.get("airline", ""),
            plane.get("icao", "")
        ):
            print(
                f"[ADSB FILTER] skipped after enrichment "
                f"callsign={plane.get('callsign','-')} "
                f"reg={plane.get('registration','-')} "
                f"airline={plane.get('airline','-')}",
                flush=True
            )
            continue

        filtered_planes.append(plane)

    planes = filtered_planes

    # Record missing logos for EVERY detected aircraft, not only
    # the subset enriched through HexDB.
    for plane in planes:
        icao = (
            plane.get("icao")
            or airline_icao_from_callsign(plane.get("callsign", ""))
        )

        if icao:
            plane["icao"] = icao
            log_missing_logo(icao, plane.get("callsign", ""))

    return planes


# ============================================================
# POZNAN AIRPORT BOARD
# ============================================================

ARRIVALS_URL = (
    "https://poznanairport.pl/en/flights/"
    "arrivals-departures/arrivals/"
)
DEPARTURES_URL = (
    "https://poznanairport.pl/en/flights/"
    "arrivals-departures/departures/"
)

ARRIVALS_URL_PL = (
    "https://poznanairport.pl/loty/"
    "przyloty-odloty/przyloty/"
)
DEPARTURES_URL_PL = (
    "https://poznanairport.pl/loty/"
    "przyloty-odloty/odloty/"
)

TIME_RE = re.compile(r"\b(?:Hour\s*)?([0-2]?\d:[0-5]\d)\b", re.I)
IATA_RE = re.compile(r"\(([A-Z]{3})\)")
FLIGHT_RE = re.compile(
    r"\b([A-Z0-9]{2,3})\s+([0-9]{1,4}[A-Z]?)\b"
)


def extract_flight_from_text(text):
    """
    Parse one POZ flight-card text block.

    Supports airline designators like:
    FR, LO, ENT, W9, 4M, 3Z.
    """
    text = " ".join(text.split())

    # Only use a labelled scheduled time, not "Last update".
    time_m = re.search(
        r"(?:Hour|Godzina)\s+([0-2]?\d:[0-5]\d)",
        text,
        re.I
    )
    if not time_m:
        return None

    iata_matches = re.findall(r"\(([A-Z]{3})\)", text.upper())
    if not iata_matches:
        return None

    candidates = []
    for m in FLIGHT_RE.finditer(text.upper()):
        prefix = m.group(1)
        number = m.group(2)

        # Must contain at least one letter: accepts W9 / 4M / 3Z,
        # rejects plain numeric fragments.
        if not any(ch.isalpha() for ch in prefix):
            continue

        if prefix in {"TO", "AT", "NO"}:
            continue

        candidates.append(prefix + number)

    if not candidates:
        return None

    flight = candidates[0]
    airport = iata_matches[0]
    scheduled = time_m.group(1)

    status = ""
    status_m = re.search(
        r"\bStatus\s+(.+?)(?:Track the flight|Śledzenie lotu|$)",
        text,
        re.I
    )
    if status_m:
        status = status_m.group(1).strip()

    gate = ""
    gate_m = re.search(
        r"\bGate\s+(?:Gate\s+)?([A-Z0-9-]+)",
        text,
        re.I
    )
    if gate_m:
        gate = gate_m.group(1)

    return {
        "time": scheduled,
        "airport": airport,
        "flight": flight,
        "status": status,
        "gate": gate
    }


def parse_poz_airport_page(html):
    """
    Robust POZ board parser.

    We do NOT depend on CSS classes or 'Track the flight' separators.
    Instead, every occurrence of:
        Hour HH:MM / Godzina HH:MM
    becomes an anchor. We then inspect the following text for:
        airport IATA, flight number, gate and status.

    This survives most layout changes on the official airport page.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = " ".join(soup.stripped_strings)
    flights = []
    seen = set()

    hour_re = re.compile(
        r"\b(?:Hour|Godzina)\s+([0-2]?\d:[0-5]\d)\b",
        re.I
    )

    for hm in hour_re.finditer(text):
        scheduled = hm.group(1)

        # The official card repeats destination + flight no. after the hour.
        # 500 chars is enough for one card without swallowing several cards.
        after = text[hm.end():hm.end() + 500]

        iata_m = re.search(r"\(([A-Z]{3})\)", after.upper())
        if not iata_m:
            continue

        flight_m = None
        for candidate in FLIGHT_RE.finditer(after.upper()):
            prefix = candidate.group(1)
            number = candidate.group(2)

            if not any(ch.isalpha() for ch in prefix):
                continue
            if prefix in {"TO", "AT", "NO"}:
                continue

            flight_m = candidate
            break

        if not flight_m:
            continue

        flight = flight_m.group(1) + flight_m.group(2)
        airport = iata_m.group(1)

        gate = ""
        gate_m = re.search(
            r"\bGate\s+(?:Gate\s+)?([A-Z0-9-]+)",
            after,
            re.I
        )
        if gate_m:
            gate = gate_m.group(1)

        status = ""
        status_m = re.search(
            r"\bStatus\s+(.{1,80}?)(?="
            r"(?:Track the flight|Śledzenie lotu|"
            r"\b(?:Hour|Godzina)\s+[0-2]?\d:[0-5]\d|$))",
            after,
            re.I
        )
        if status_m:
            status = status_m.group(1).strip()

        key = (scheduled, airport, flight)
        if key in seen:
            continue

        seen.add(key)
        flights.append({
            "time": scheduled,
            "airport": airport,
            "flight": flight,
            "status": status,
            "gate": gate
        })

    return flights

def minutes_from_midnight(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def choose_board_rows(flights, count=4):
    """
    Board logic:
      - if there are future flights today -> show the next 4
      - if there are NO future flights today -> show the last 4 of the day

    This applies equally to arrivals and departures.
    """
    if not flights:
        return []

    now = datetime.now(WARSAW_TZ)
    now_min = now.hour * 60 + now.minute

    def sort_key(f):
        try:
            return minutes_from_midnight(f["time"])
        except Exception:
            return 9999

    flights = sorted(flights, key=sort_key)

    future = [
        f for f in flights
        if sort_key(f) >= now_min
    ]

    if future:
        return future[:count]

    # Nothing left in the future -> final four operations of today.
    return flights[-count:]

def compact_status(row, arrivals):
    status = (row.get("status") or "").upper().strip()
    gate = (row.get("gate") or "").upper().strip()

    if "CANCEL" in status or "ODWOL" in status:
        return "CANCEL"
    if "DELAY" in status or "OPOZN" in status:
        return "DELAY"
    if "BOARD" in status:
        return "BOARD"
    if "LANDED" in status or "WYLADOW" in status:
        return "LANDED"
    if "LUGGAGE" in status or "BAGAZ" in status:
        return "BAGS"
    if "DEPART" in status or "WYSTART" in status:
        return "DEPART"
    if "ON TIME" in status:
        return "ON TIME"
    if gate and not arrivals:
        return ("G" + gate)[:6]

    # Some boards publish a revised time inside status.
    tm = TIME_RE.search(status)
    if tm:
        return tm.group(1)

    if status:
        cleaned = re.sub(r"[^A-Z0-9:]", "", status)
        return cleaned[:6]

    return "--"



# ICAO airline callsign prefix -> IATA/commercial flight designator.
# Used ONLY for matching ADS-B callsigns against the official POZ board.
ICAO_TO_IATA_AIRLINE = {
    "RYR": "FR",   # Ryanair
    "RYS": "RR",   # Buzz
    "LOT": "LO",   # LOT
    "WZZ": "W6",   # Wizz Air
    "WUK": "W9",   # Wizz Air UK
    "WMT": "W4",   # Wizz Air Malta
    "ENT": "ENT",  # Enter Air on POZ board
    "TVP": "3Z",   # Smartwings Poland / Travel Service Polska
    "DLH": "LH",
    "KLM": "KL",
    "SAS": "SK",
    "AUA": "OS",
    "SWR": "LX",
    "AFR": "AF",
    "BAW": "BA",
    "EZY": "U2",
    "EWG": "EW",
    "TAP": "TP",
    "FIN": "AY",
    "BEL": "SN",
    "IBE": "IB",
    "AEE": "A3",
    "THY": "TK",
    "QTR": "QR",
    "UAE": "EK",
    "ELY": "LY",
    "ITY": "AZ",
    "TRA": "HV",
    "VOE": "V7",
    "VLG": "VY",
    "NSZ": "D8",
    "NOZ": "DY",
    "SEH": "GQ",
}


def flight_suffix(value):
    """
    Return the part after an airline designator.

    Examples:
      FR2193   -> 2193
      W95390   -> 5390
      RYR2193  -> 2193  (after the three-letter callsign prefix)
    """
    value = normalize_flight_number(value)

    # Commercial designator: 2-3 alphanumeric chars, then flight suffix.
    m = re.match(r"^[A-Z0-9]{2,3}([0-9][A-Z0-9]{0,5})$", value)
    if m:
        suffix = m.group(1)
    else:
        # ADS-B callsign: normally 3 letters followed by a suffix.
        m = re.match(r"^[A-Z]{3}([0-9][A-Z0-9]{0,5})$", value)
        suffix = m.group(1) if m else ""

    if not suffix:
        return ""

    # Normalize purely numeric leading zeroes.
    m_num = re.match(r"^0*([0-9]+)([A-Z]?)$", suffix)
    if m_num:
        number = str(int(m_num.group(1))) if m_num.group(1) else "0"
        return number + m_num.group(2)

    return suffix


def callsign_to_board_flight(callsign):
    """
    Convert an ICAO ADS-B callsign to the most likely commercial flight no.

    Example:
      RYR2193 -> FR2193
      LOT3947 -> LO3947
      WUK5390 -> W95390
    """
    callsign = clean_callsign(callsign)
    m = re.match(r"^([A-Z]{3})([0-9][A-Z0-9]{0,5})$", callsign)
    if not m:
        return ""

    icao_airline, suffix = m.groups()
    iata_airline = ICAO_TO_IATA_AIRLINE.get(icao_airline)
    if not iata_airline:
        return ""

    return normalize_flight_number(iata_airline + suffix)


def build_poz_route_index(arrivals, departures):
    """
    Build a full-day route lookup from the official POZ airport board.

    Arrival row:
        other airport -> POZ
    Departure row:
        POZ -> other airport
    """
    by_flight = {}
    by_suffix = {}

    def add_row(row, direction):
        flight = normalize_flight_number(row.get("flight"))
        other = (row.get("airport") or "").strip().upper()

        if not flight or len(other) != 3:
            return

        if direction == "arrival":
            origin, destination = other, "POZ"
        else:
            origin, destination = "POZ", other

        item = {
            "flight": flight,
            "origin": origin,
            "destination": destination,
            "direction": direction,
            "time": row.get("time") or ""
        }

        by_flight.setdefault(flight, []).append(item)

        suffix = flight_suffix(flight)
        if suffix:
            by_suffix.setdefault(suffix, []).append(item)

    for row in arrivals:
        add_row(row, "arrival")

    for row in departures:
        add_row(row, "departure")

    return {
        "by_flight": by_flight,
        "by_suffix": by_suffix
    }


def update_poz_route_index(arrivals, departures):
    global POZ_ROUTE_INDEX

    if not arrivals and not departures:
        return

    POZ_ROUTE_INDEX = build_poz_route_index(arrivals, departures)
    safe_json_save(POZ_ROUTE_CACHE_PATH, POZ_ROUTE_INDEX)

    print(
        "[POZ ROUTES]",
        f"flights={len(POZ_ROUTE_INDEX.get('by_flight', {}))}",
        f"suffixes={len(POZ_ROUTE_INDEX.get('by_suffix', {}))}",
        flush=True
    )



def board_time_distance_minutes(hhmm, now=None):
    """Circular distance between current local time and board HH:MM."""
    if now is None:
        now = datetime.now(WARSAW_TZ)

    try:
        target = minutes_from_midnight(hhmm)
    except Exception:
        return 99999

    current = now.hour * 60 + now.minute
    diff = abs(target - current)
    return min(diff, 1440 - diff)


def nearest_poz_candidate(callsign, direction):
    """
    Pick the same-airline POZ board operation nearest to current time.
    direction: 'arrival' or 'departure'
    """
    candidates = poz_candidates_for_callsign(callsign, direction)
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: board_time_distance_minutes(
            item.get("time", "")
        )
    )

    result = dict(candidates[0])
    result["match"] = f"vs-nearest-{direction}"
    result["time_distance_min"] = board_time_distance_minutes(
        result.get("time", "")
    )
    return result

def route_from_poz_board(callsign, vertical_speed=None):
    """
    POZ-board fallback.

    Priority:
      1. Exact converted commercial flight number.
      2. If exact match fails:
           VS < 0 -> nearest same-airline ARRIVAL
           VS > 0 -> nearest same-airline DEPARTURE
      3. Unique suffix fallback.
    """
    callsign = clean_callsign(callsign)
    if not callsign:
        return None

    by_flight = POZ_ROUTE_INDEX.get("by_flight", {})
    by_suffix = POZ_ROUTE_INDEX.get("by_suffix", {})

    # 1) Exact mapped flight-number match.
    board_flight = callsign_to_board_flight(callsign)
    if board_flight:
        matches = by_flight.get(board_flight, [])
        if len(matches) == 1:
            result = dict(matches[0])
            result["match"] = "exact"
            return result

        routes = {
            (m.get("origin"), m.get("destination"))
            for m in matches
        }
        if matches and len(routes) == 1:
            result = dict(matches[0])
            result["match"] = "exact"
            return result

    # 2) Tactical/alphanumeric callsign: use VS sign.
    try:
        vs = float(vertical_speed) if vertical_speed is not None else 0.0
    except Exception:
        vs = 0.0

    if vs < 0:
        result = nearest_poz_candidate(callsign, "arrival")
        if result:
            result["vertical_speed"] = vs
            return result
    elif vs > 0:
        result = nearest_poz_candidate(callsign, "departure")
        if result:
            result["vertical_speed"] = vs
            return result

    # 3) Conservative unique-suffix fallback.
    suffix = flight_suffix(callsign)
    if suffix:
        matches = by_suffix.get(suffix, [])
        routes = {
            (m.get("origin"), m.get("destination"))
            for m in matches
        }
        if len(matches) == 1 or (matches and len(routes) == 1):
            result = dict(matches[0])
            result["match"] = "unique-suffix"
            return result

    return None

def poz_candidates_for_callsign(callsign, direction="any"):
    """
    Diagnostic helper: return same-airline POZ-board candidates.

    Useful for tactical/alphanumeric callsigns such as ENT6CA where the
    ADS-B callsign may not equal the published commercial flight number.
    """
    callsign = clean_callsign(callsign)
    m = re.match(r"^([A-Z]{3})", callsign)
    if not m:
        return []

    airline_icao = m.group(1)
    board_prefix = ICAO_TO_IATA_AIRLINE.get(airline_icao, airline_icao)

    rows = []
    for flight, matches in POZ_ROUTE_INDEX.get("by_flight", {}).items():
        if not flight.startswith(board_prefix):
            continue

        for item in matches:
            if direction != "any" and item.get("direction") != direction:
                continue
            rows.append(dict(item))

    def key(item):
        try:
            return minutes_from_midnight(item.get("time", "99:99"))
        except Exception:
            return 9999

    rows.sort(key=key)
    return rows

def fetch_one_board(primary_url, fallback_url, raw_path=None):
    """
    English official board first; Polish official board as fallback.
    Saves raw HTML when requested so debugging is possible even when parsing fails.
    """
    last_error = None

    for url in (primary_url, fallback_url):
        try:
            print(f"[POZ FETCH] GET {url}", flush=True)

            r = SESSION.get(url, timeout=HTTP_TIMEOUT)
            print(
                f"[POZ FETCH] HTTP {r.status_code}, {len(r.content)} bytes",
                flush=True
            )
            r.raise_for_status()

            if raw_path is not None:
                raw_path.write_text(r.text, encoding="utf-8")

            parsed = parse_poz_airport_page(r.text)

            print(
                f"[POZ FETCH] parsed {len(parsed)} flights from {url}",
                flush=True
            )

            if parsed:
                return parsed, ""

            last_error = f"0 parsed flights from {url}"

        except Exception as exc:
            last_error = f"{url}: {type(exc).__name__}: {exc}"
            print(f"[POZ FETCH] ERROR {last_error}", flush=True)

    return [], last_error or "unknown board error"

def fetch_airport_board():
    result = {
        "arrivals": [],
        "departures": [],
        "updated_at": datetime.now(WARSAW_TZ).isoformat()
    }

    errors = []

    arrivals_raw, arr_error = fetch_one_board(
        ARRIVALS_URL,
        ARRIVALS_URL_PL,
        ARRIVALS_RAW_PATH
    )
    departures_raw, dep_error = fetch_one_board(
        DEPARTURES_URL,
        DEPARTURES_URL_PL,
        DEPARTURES_RAW_PATH
    )

    # Keep a full-day index for aircraft-route fallback BEFORE reducing
    # the board to four rows for the LED display.
    update_poz_route_index(arrivals_raw, departures_raw)

    result["arrivals"] = choose_board_rows(arrivals_raw, 4)
    result["departures"] = choose_board_rows(departures_raw, 4)

    if arr_error:
        errors.append("arrivals: " + arr_error)
    if dep_error:
        errors.append("departures: " + dep_error)

    old = safe_json_load(AIRPORT_CACHE_PATH, {})

    for name in ("arrivals", "departures"):
        if not result[name] and old.get(name):
            result[name] = old[name]

    result["errors"] = errors
    result["debug"] = {
        "arrivals_parsed": len(arrivals_raw),
        "departures_parsed": len(departures_raw),
        "arrivals_displayed": len(result["arrivals"]),
        "departures_displayed": len(result["departures"])
    }

    safe_json_save(AIRPORT_CACHE_PATH, result)

    # Always create a human-readable debug file.
    lines = [
        "FlightWall airport board diagnostic",
        f"Updated: {result['updated_at']}",
        f"Arrivals parsed: {len(arrivals_raw)}",
        f"Departures parsed: {len(departures_raw)}",
        f"Arrivals displayed: {len(result['arrivals'])}",
        f"Departures displayed: {len(result['departures'])}",
        "",
        "DEPARTURES DISPLAYED:"
    ]

    for f in result["departures"]:
        lines.append(
            f"{f.get('time')} {f.get('airport')} "
            f"{f.get('flight')} gate={f.get('gate')} "
            f"status={f.get('status')}"
        )

    lines += ["", "ERRORS:"]
    lines += errors if errors else ["none"]

    AIRPORT_DEBUG_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    print(
        "[POZ BOARD]",
        f"arrivals={len(arrivals_raw)}",
        f"departures={len(departures_raw)}",
        f"display_dep={len(result['departures'])}",
        ("errors=" + " | ".join(errors)) if errors else "OK",
        flush=True
    )

    return result



# ============================================================
# EPPO METAR WEATHER
# ============================================================

def _metar_signed_temp(token):
    if token is None:
        return None

    token = str(token).strip().upper()
    if not token:
        return None

    try:
        if token.startswith("M"):
            return -float(token[1:])
        return float(token)
    except Exception:
        return None


def weather_condition_from_metar(raw_metar):
    """
    Convert a raw METAR into a simple display condition.

    Priority:
      thunder -> rain -> snow -> fog -> cloudy -> partly_cloudy -> clear
    """
    metar = (raw_metar or "").upper()

    if "TS" in metar:
        return "thunder"

    if any(token in metar for token in (
        "RA", "DZ", "SHRA", "SHDZ", "FZRA", "FZDZ"
    )):
        return "rain"

    if any(token in metar for token in (
        "SN", "SG", "PL", "SHSN"
    )):
        return "snow"

    if any(token in metar for token in (
        " FG", " BR", " HZ", " FU"
    )):
        return "fog"

    if "OVC" in metar or "BKN" in metar:
        return "cloudy"

    if "SCT" in metar or "FEW" in metar:
        return "partly_cloudy"

    if "CAVOK" in metar or "CLR" in metar or "SKC" in metar or "NSC" in metar:
        return "clear"

    return "clear"


def fetch_poz_weather():
    """
    Get current aviation weather for Poznan-Lawica (EPPO).

    Source: AviationWeather.gov METAR JSON.
    The parser uses decoded JSON fields when available and falls back
    to the raw METAR string for wind / temperature.
    """
    station = str(CONFIG["weather"].get("station", "EPPO")).upper()
    url = (
        "https://aviationweather.gov/api/data/metar"
        f"?ids={station}&format=json"
    )

    r = SESSION.get(url, timeout=HTTP_TIMEOUT)

    if r.status_code == 204:
        return {}

    r.raise_for_status()
    payload = r.json()

    if isinstance(payload, list):
        if not payload:
            return {}
        obs = payload[0]
    elif isinstance(payload, dict):
        obs = payload
    else:
        return {}

    raw_metar = (
        obs.get("rawOb")
        or obs.get("raw_text")
        or obs.get("raw")
        or ""
    )

    temp_c = (
        obs.get("temp")
        if obs.get("temp") is not None
        else obs.get("tempC")
    )
    wind_dir = (
        obs.get("wdir")
        if obs.get("wdir") is not None
        else obs.get("wind_dir_degrees")
    )
    wind_speed = (
        obs.get("wspd")
        if obs.get("wspd") is not None
        else obs.get("wind_speed_kt")
    )
    wind_gust = (
        obs.get("wgst")
        if obs.get("wgst") is not None
        else obs.get("wind_gust_kt")
    )

    # Raw METAR fallback, e.g. 25012G20KT / VRB03KT.
    wind_match = re.search(
        r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b",
        raw_metar.upper()
    )
    if wind_match:
        if wind_dir is None:
            wind_dir = wind_match.group(1)
        if wind_speed is None:
            wind_speed = wind_match.group(2)
        if wind_gust is None and wind_match.group(3):
            wind_gust = wind_match.group(3)

    # Raw METAR temperature fallback, e.g. 18/12 or M02/M05.
    temp_match = re.search(
        r"\b(M?\d{2})/(M?\d{2})\b",
        raw_metar.upper()
    )
    if temp_c is None and temp_match:
        temp_c = _metar_signed_temp(temp_match.group(1))

    try:
        temp_c = float(temp_c) if temp_c is not None else None
    except Exception:
        temp_c = None

    try:
        # Keep VRB as text.
        if str(wind_dir).upper() != "VRB":
            wind_dir = int(float(wind_dir))
        else:
            wind_dir = "VRB"
    except Exception:
        wind_dir = None

    try:
        wind_speed = int(round(float(wind_speed)))
    except Exception:
        wind_speed = None

    try:
        wind_gust = int(round(float(wind_gust)))
    except Exception:
        wind_gust = None

    return {
        "station": station,
        "temp_c": temp_c,
        "wind_dir": wind_dir,
        "wind_speed_kt": wind_speed,
        "wind_gust_kt": wind_gust,
        "raw_metar": raw_metar,
        "condition": weather_condition_from_metar(raw_metar)
    }

# ============================================================
# LIVE STATE / BACKGROUND POLLERS
# ============================================================

class LiveState:
    def __init__(self):
        self.lock = threading.Lock()
        self.aircraft = []
        self.arrivals = []
        self.departures = []
        self.weather = {}

        self.aircraft_error = ""
        self.airport_error = ""
        self.weather_error = ""

        self.aircraft_updated = None
        self.airport_updated = None
        self.weather_updated = None

        self.stop_event = threading.Event()
        self.force_adsb = threading.Event()
        self.force_airport = threading.Event()
        self.force_weather = threading.Event()

    def snapshot(self):
        with self.lock:
            return {
                "aircraft": [dict(x) for x in self.aircraft],
                "arrivals": [dict(x) for x in self.arrivals],
                "departures": [dict(x) for x in self.departures],
                "weather": dict(self.weather),
                "aircraft_error": self.aircraft_error,
                "airport_error": self.airport_error,
                "weather_error": self.weather_error,
                "aircraft_updated": self.aircraft_updated,
                "airport_updated": self.airport_updated,
                "weather_updated": self.weather_updated
            }


def adsb_worker(state):
    interval = int(CONFIG["refresh"]["adsb_seconds"])

    while not state.stop_event.is_set():
        try:
            planes = fetch_nearby_aircraft()
            with state.lock:
                state.aircraft = planes
                state.aircraft_error = ""
                state.aircraft_updated = datetime.now(WARSAW_TZ)
        except Exception as exc:
            msg = str(exc)

            if msg.startswith("ADSB_RATE_LIMIT:"):
                try:
                    retry_after = int(msg.split(":", 1)[1])
                except Exception:
                    retry_after = 60

                print(
                    f"[ADSB 429] Rate limit. Waiting {retry_after}s "
                    "before the next request.",
                    flush=True
                )

                # Keep the last successful aircraft list on screen.
                with state.lock:
                    state.aircraft_error = (
                        f"RATE LIMIT - retry in {retry_after}s"
                    )

                # Extra wait here prevents immediately hammering the API again.
                state.stop_event.wait(retry_after)
            else:
                error_text = f"{type(exc).__name__}: {exc}"
                print(f"[ADSB ERROR] {error_text}", flush=True)
                with state.lock:
                    state.aircraft_error = error_text

        # Wait, but wake early on manual refresh.
        state.force_adsb.wait(interval)
        state.force_adsb.clear()


def airport_worker(state):
    interval = int(CONFIG["refresh"]["airport_seconds"])

    while not state.stop_event.is_set():
        try:
            board = fetch_airport_board()
            with state.lock:
                state.arrivals = board.get("arrivals", [])
                state.departures = board.get("departures", [])
                state.airport_error = "; ".join(board.get("errors", []))
                state.airport_updated = datetime.now(WARSAW_TZ)
        except Exception as exc:
            with state.lock:
                state.airport_error = str(exc)

        state.force_airport.wait(interval)
        state.force_airport.clear()


def weather_worker(state):
    interval = int(CONFIG["weather"]["refresh_seconds"])

    while not state.stop_event.is_set():
        try:
            weather = fetch_poz_weather()
            with state.lock:
                state.weather = weather
                state.weather_error = ""
                state.weather_updated = datetime.now(WARSAW_TZ)

            if weather:
                print(
                    "[EPPO METAR]",
                    f"T={weather.get('temp_c')}",
                    f"W={weather.get('wind_dir')}/"
                    f"{weather.get('wind_speed_kt')}KT",
                    flush=True
                )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"[WEATHER ERROR] {error_text}", flush=True)
            with state.lock:
                state.weather_error = error_text

        state.force_weather.wait(interval)
        state.force_weather.clear()


# ============================================================
# DRAWING PRIMITIVES
# ============================================================

def make_buffer():
    return [[None for _ in range(MATRIX_W)] for _ in range(MATRIX_H)]


def set_pixel(buf, x, y, color):
    if 0 <= x < MATRIX_W and 0 <= y < MATRIX_H:
        buf[y][x] = color


def draw_char(buf, ch, x, y, color, scale=1):
    pattern = FONT_5X7.get(ch.upper(), FONT_5X7["?"])

    for row, line in enumerate(pattern):
        for col, bit in enumerate(line):
            if bit == "1":
                for sy in range(scale):
                    for sx in range(scale):
                        set_pixel(
                            buf,
                            x + col * scale + sx,
                            y + row * scale + sy,
                            color
                        )


def text_width(text, scale=1, spacing=1):
    if not text:
        return 0
    return len(text) * (5 * scale + spacing) - spacing


def draw_text(buf, text, x, y, color, scale=1, spacing=1):
    cursor = x
    for ch in str(text):
        draw_char(buf, ch, cursor, y, color, scale)
        cursor += 5 * scale + spacing


def draw_centered(buf, text, y, color, scale=1, spacing=1):
    width = text_width(text, scale, spacing)
    draw_text(
        buf,
        text,
        max(0, (MATRIX_W - width) // 2),
        y,
        color,
        scale,
        spacing
    )


def draw_hline(buf, x1, x2, y, color):
    for x in range(x1, x2 + 1):
        set_pixel(buf, x, y, color)


def draw_vline(buf, y1, y2, x, color):
    for y in range(y1, y2 + 1):
        set_pixel(buf, x, y, color)


def draw_box(buf, x1, y1, x2, y2, color):
    draw_hline(buf, x1, x2, y1, color)
    draw_hline(buf, x1, x2, y2, color)
    draw_vline(buf, y1, y2, x1, color)
    draw_vline(buf, y1, y2, x2, color)


def draw_centered_in_box(buf, text, x1, y1, x2, y2, color):
    width = text_width(text)
    height = 7
    x = x1 + ((x2 - x1 + 1) - width) // 2
    y = y1 + ((y2 - y1 + 1) - height) // 2
    draw_text(buf, text, x, y, color)


def draw_plane_icon(buf, x, y, color):
    pixels = [
        (3,0),
        (3,1),
        (2,2),(3,2),(4,2),
        (0,3),(1,3),(2,3),(3,3),(4,3),(5,3),(6,3),
        (2,4),(3,4),(4,4),
        (3,5),
        (2,6),(3,6),(4,6),
    ]
    for px, py in pixels:
        set_pixel(buf, x + px, y + py, color)



LOGO_COLOR_CACHE = {}


def has_airline_logo(icao):
    icao = (icao or "").upper()
    return bool(icao) and (LOGO_DIR / f"{icao}.png").exists()


def dominant_logo_color(icao, fallback=CYAN):
    """
    Return the dominant vivid color from the airline logo.
    Transparent pixels, near-black, near-white and neutral grays are ignored.
    Result is cached.
    """
    icao = (icao or "").upper()

    if icao in LOGO_COLOR_CACHE:
        return LOGO_COLOR_CACHE[icao]

    logo_path = LOGO_DIR / f"{icao}.png"
    if not logo_path.exists():
        LOGO_COLOR_CACHE[icao] = fallback
        return fallback

    try:
        image = pygame.image.load(str(logo_path))
        buckets = {}

        for y in range(image.get_height()):
            for x in range(image.get_width()):
                c = image.get_at((x, y))

                if len(c) >= 4 and c.a < 40:
                    continue

                r, g, b = c.r, c.g, c.b

                # Ignore LED-off / near-black
                if r < 18 and g < 18 and b < 18:
                    continue

                # Ignore white / almost white
                if r > 235 and g > 235 and b > 235:
                    continue

                # Ignore weak grays
                if max(r, g, b) - min(r, g, b) < 24:
                    continue

                # Quantize to group very similar shades.
                key = (
                    min(255, (r // 24) * 24),
                    min(255, (g // 24) * 24),
                    min(255, (b // 24) * 24),
                )
                buckets[key] = buckets.get(key, 0) + 1

        if buckets:
            color = max(buckets, key=buckets.get)
        else:
            color = fallback

        LOGO_COLOR_CACHE[icao] = color
        return color

    except pygame.error:
        LOGO_COLOR_CACHE[icao] = fallback
        return fallback


def normalize_compare_token(value):
    """
    Uppercase and strip non-alphanumeric chars for safe comparisons.
    """
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def should_exclude_aircraft(registration, callsign, airline, icao=""):
    """
    Completely remove unwanted ADS-B targets from the display list.

    Exclude when:
      1. callsign is explicitly ignored (e.g. TXLU05)
      2. registration is explicitly ignored
      3. airline / inferred ICAO operator is TXL
      4. normalized registration equals normalized callsign
    """
    reg_norm = normalize_compare_token(registration)
    call_norm = normalize_compare_token(callsign)
    airline_norm = (airline or "").strip().upper()
    icao_norm = (icao or "").strip().upper()

    # If ICAO wasn't passed, infer it from callsign.
    if not icao_norm:
        icao_norm = airline_icao_from_callsign(callsign)

    if reg_norm in IGNORED_REGISTRATIONS:
        return True

    if call_norm in IGNORED_CALLSIGNS:
        return True

    if airline_norm in IGNORED_AIRLINE_ICAO:
        return True

    if icao_norm in IGNORED_AIRLINE_ICAO:
        return True

    if reg_norm and call_norm and reg_norm == call_norm:
        return True

    return False


POZ_MOSAIC_COLORS = [
    (22, 110, 186),   # dark blue
    (50, 186, 233),   # cyan
    (244, 244, 244),  # white
    (245, 0, 127),    # pink
    (50, 186, 233),   # cyan
    (22, 110, 186),   # dark blue
    (245, 0, 127),    # pink
    (244, 244, 244),  # white
]


def draw_poz_mosaic_line(buf, y, block_w=4, offset=0):
    """
    Draw a 1-pixel mosaic line inspired by the Poznan Lawica logo palette.
    """
    for x in range(128):
        idx = ((x + offset) // block_w) % len(POZ_MOSAIC_COLORS)
        set_pixel(buf, x, y, POZ_MOSAIC_COLORS[idx])

def draw_poz_mosaic_frame(buf, block_len=4):
    """
    1-pixel mosaic frame around the entire 128x64 display.
    Uses the same Poznan-Lawica palette as arrivals/departures.
    """
    # Top and bottom.
    for x in range(MATRIX_W):
        top_idx = (x // block_len) % len(POZ_MOSAIC_COLORS)
        bottom_idx = ((x // block_len) + 2) % len(POZ_MOSAIC_COLORS)

        set_pixel(buf, x, 0, POZ_MOSAIC_COLORS[top_idx])
        set_pixel(buf, x, MATRIX_H - 1, POZ_MOSAIC_COLORS[bottom_idx])

    # Left and right.
    for y in range(MATRIX_H):
        left_idx = ((y // block_len) + 1) % len(POZ_MOSAIC_COLORS)
        right_idx = ((y // block_len) + 3) % len(POZ_MOSAIC_COLORS)

        set_pixel(buf, 0, y, POZ_MOSAIC_COLORS[left_idx])
        set_pixel(buf, MATRIX_W - 1, y, POZ_MOSAIC_COLORS[right_idx])


def draw_airline_logo(buf, icao, x1, y1, x2, y2, fallback_color):
    icao = (icao or "").upper()
    logo_path = LOGO_DIR / f"{icao}.png"

    # No placeholder box: leave empty space if logo file is missing.
    if not icao or not logo_path.exists():
        return

    try:
        image = pygame.image.load(str(logo_path))

        max_w = x2 - x1 + 1
        max_h = y2 - y1 + 1
        src_w, src_h = image.get_size()

        ratio = min(max_w / src_w, max_h / src_h)
        new_w = max(1, int(src_w * ratio))
        new_h = max(1, int(src_h * ratio))

        image = pygame.transform.smoothscale(
            image, (new_w, new_h)
        )

        start_x = x1 + (max_w - new_w) // 2
        start_y = y1 + (max_h - new_h) // 2

        for py in range(new_h):
            for px in range(new_w):
                c = image.get_at((px, py))

                if len(c) >= 4 and c.a < 40:
                    continue

                # Treat almost-black as LED-off.
                if c.r < 12 and c.g < 12 and c.b < 12:
                    continue

                set_pixel(
                    buf,
                    start_x + px,
                    start_y + py,
                    (c.r, c.g, c.b)
                )
    except pygame.error:
        # On logo decode failure, also leave the area empty.
        return




def draw_circle(buf, cx, cy, radius, color):
    """Simple midpoint circle for the 128x64 pixel canvas."""
    x = radius
    y = 0
    err = 0

    while x >= y:
        points = [
            (cx + x, cy + y), (cx + y, cy + x),
            (cx - y, cy + x), (cx - x, cy + y),
            (cx - x, cy - y), (cx - y, cy - x),
            (cx + y, cy - x), (cx + x, cy - y),
        ]
        for px, py in points:
            set_pixel(buf, px, py, color)

        y += 1
        if err <= 0:
            err += 2 * y + 1
        if err > 0:
            x -= 1
            err -= 2 * x + 1


def project_to_radar(lat, lon, cx, cy, radius_px, range_km):
    """
    Project lat/lon onto a local radar centred on HOME_LAT/HOME_LON.
    Returns (x, y, distance_km).
    """
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(HOME_LAT))

    dx_km = (float(lon) - HOME_LON) * km_per_deg_lon
    dy_km = (float(lat) - HOME_LAT) * km_per_deg_lat
    distance_km = math.hypot(dx_km, dy_km)

    if range_km <= 0:
        return cx, cy, distance_km

    scale = radius_px / float(range_km)
    x = int(round(cx + dx_km * scale))
    y = int(round(cy - dy_km * scale))

    return x, y, distance_km


def draw_radar_dot(buf, x, y, color):
    set_pixel(buf, x, y, color)
    set_pixel(buf, x + 1, y, color)
    set_pixel(buf, x, y + 1, color)
    set_pixel(buf, x + 1, y + 1, color)


def draw_location_marker(buf, x, y, color):
    """
    5-pixel diamond marker, visually different from aircraft dots.
    """
    set_pixel(buf, x, y - 1, color)
    set_pixel(buf, x - 1, y, color)
    set_pixel(buf, x, y, color)
    set_pixel(buf, x + 1, y, color)
    set_pixel(buf, x, y + 1, color)


def airline_color_for_plane(plane):
    """
    Use the dominant vivid colour extracted from the airline logo.
    Falls back to the old manual airline colour / white if no logo exists.
    """
    icao = (
        plane.get("icao")
        or airline_icao_from_callsign(plane.get("callsign", ""))
        or ""
    ).upper()

    fallback = airline_color(icao) if icao else WHITE
    return dominant_logo_color(icao, fallback)


def radar_aircraft_color(plane):
    # Every aircraft dot now uses its airline/logo colour.
    return airline_color_for_plane(plane)


def draw_weather_sun(buf, x, y):
    color = YELLOW

    # 5x5 sun core.
    for py in range(y + 2, y + 7):
        for px in range(x + 2, x + 7):
            if (px - (x + 4)) ** 2 + (py - (y + 4)) ** 2 <= 5:
                set_pixel(buf, px, py, color)

    # Rays.
    for px, py in [
        (x + 4, y),
        (x + 4, y + 8),
        (x, y + 4),
        (x + 8, y + 4),
        (x + 1, y + 1),
        (x + 7, y + 1),
        (x + 1, y + 7),
        (x + 7, y + 7),
    ]:
        set_pixel(buf, px, py, color)


def draw_weather_cloud(buf, x, y, color=WHITE):
    # Compact 10x6 cloud.
    pixels = [
        (3, 0), (4, 0), (5, 0),
        (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
        (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2),
        (0, 3), (1, 3), (2, 3), (3, 3), (4, 3),
        (5, 3), (6, 3), (7, 3), (8, 3),
        (1, 4), (2, 4), (3, 4), (4, 4), (5, 4), (6, 4), (7, 4),
    ]

    for px, py in pixels:
        set_pixel(buf, x + px, y + py, color)


def draw_weather_rain(buf, x, y):
    draw_weather_cloud(buf, x, y, GRAY)

    # Blue/cyan raindrops.
    for px, py in [
        (2, 6), (2, 7),
        (5, 6), (5, 7),
        (8, 6), (8, 7),
    ]:
        set_pixel(buf, x + px, y + py, CYAN)


def draw_weather_thunder(buf, x, y):
    draw_weather_cloud(buf, x, y, GRAY)

    # Tiny yellow lightning bolt.
    for px, py in [
        (5, 5),
        (4, 6),
        (5, 6),
        (4, 7),
        (3, 8),
    ]:
        set_pixel(buf, x + px, y + py, YELLOW)


def draw_weather_snow(buf, x, y):
    draw_weather_cloud(buf, x, y, GRAY)

    for px, py in [
        (2, 6), (2, 8), (1, 7), (3, 7),
        (7, 6), (7, 8), (6, 7), (8, 7),
    ]:
        set_pixel(buf, x + px, y + py, WHITE)


def draw_weather_fog(buf, x, y):
    draw_weather_cloud(buf, x, y, GRAY)
    draw_hline(buf, x, x + 8, y + 6, GRAY)
    draw_hline(buf, x + 1, x + 7, y + 8, GRAY)


def draw_weather_partly_cloudy(buf, x, y):
    # Sun slightly behind cloud.
    for px, py in [
        (6, 0), (5, 1), (6, 1), (7, 1),
        (4, 2), (5, 2), (6, 2), (7, 2), (8, 2),
        (6, 3),
    ]:
        set_pixel(buf, x + px, y + py, YELLOW)

    draw_weather_cloud(buf, x, y + 3, WHITE)


def draw_weather_icon(buf, x, y, condition):
    condition = (condition or "clear").lower()

    if condition == "thunder":
        draw_weather_thunder(buf, x, y)
    elif condition == "rain":
        draw_weather_rain(buf, x, y)
    elif condition == "snow":
        draw_weather_snow(buf, x, y)
    elif condition == "fog":
        draw_weather_fog(buf, x, y)
    elif condition == "cloudy":
        draw_weather_cloud(buf, x, y + 2, GRAY)
    elif condition == "partly_cloudy":
        draw_weather_partly_cloudy(buf, x, y)
    else:
        draw_weather_sun(buf, x, y)


def radar_visible_planes(planes):
    """
    Return aircraft that really fit inside the configured 40 NM radar.
    The order is inherited from the ADS-B list, so every radar pass is stable.
    """
    cx, cy = 31, 32
    radius_px = 29

    range_nm = float(CONFIG["radar"].get("range_nm", 40))
    range_km = range_nm * 1.852

    visible_planes = []

    for plane in planes:
        lat = plane.get("lat")
        lon = plane.get("lon")
        if lat is None or lon is None:
            continue

        try:
            ax, ay, distance_km = project_to_radar(
                lat, lon, cx, cy, radius_px, range_km
            )
        except Exception:
            continue

        if distance_km > range_km:
            continue

        if math.hypot(ax - cx, ay - cy) > radius_px:
            continue

        item = dict(plane)
        item["_radar_x"] = ax
        item["_radar_y"] = ay
        item["_radar_color"] = radar_aircraft_color(plane)
        visible_planes.append(item)

    return visible_planes


def render_radar(planes, weather, radar_elapsed_ms=0):
    """
    Full-height 40 NM local radar.

      green diamond = home
      blue diamond  = Poznan-Lawica
      aircraft dots = dominant airline-logo colour

    Every visible aircraft receives one focus slot of `focus_seconds`.
    The focused aircraft blinks and its callsign is shown on the right.
    The screen is allowed to leave only after the full list has been shown.
    """
    buf = make_buffer()

    # Nearly full panel height: 59 px diameter, y=3..61.
    cx, cy = 31, 32
    radius_px = 29

    range_nm = float(CONFIG["radar"].get("range_nm", 40))
    range_km = range_nm * 1.852

    focus_seconds = max(
        0.5,
        float(CONFIG["radar"].get("focus_seconds", 3))
    )
    blink_ms = max(
        100,
        int(CONFIG["radar"].get("blink_ms", 350))
    )

    # Radar rings.
    draw_circle(buf, cx, cy, radius_px, GRAY)
    draw_circle(buf, cx, cy, 19, (52, 52, 62))
    draw_circle(buf, cx, cy, 10, (42, 42, 52))

    # Faint crosshair.
    for d in range(-radius_px + 2, radius_px - 1):
        if d % 3 == 0:
            set_pixel(buf, cx + d, cy, (35, 35, 44))
            set_pixel(buf, cx, cy + d, (35, 35, 44))

    # HOME: green diamond in the radar centre.
    draw_location_marker(buf, cx, cy, GREEN)

    # POZ: Poznan-Airport pink diamond at its actual position.
    px, py, airport_distance = project_to_radar(
        POZ_LAT, POZ_LON, cx, cy, radius_px, range_km
    )
    if airport_distance <= range_km:
        draw_location_marker(buf, px, py, (245, 0, 127))

    visible_planes = radar_visible_planes(planes)

    focused_index = None
    focused_plane = None

    if visible_planes:
        focus_slot_ms = max(1, int(focus_seconds * 1000))
        focused_index = min(
            int(radar_elapsed_ms // focus_slot_ms),
            len(visible_planes) - 1
        )
        focused_plane = visible_planes[focused_index]

    # All non-focused aircraft stay visible continuously.
    for idx, plane in enumerate(visible_planes):
        if idx == focused_index:
            continue

        draw_radar_dot(
            buf,
            plane["_radar_x"],
            plane["_radar_y"],
            plane["_radar_color"]
        )

    # Focused aircraft blinks throughout its 3-second slot.
    if focused_plane is not None:
        blink_on = ((int(radar_elapsed_ms) // blink_ms) % 2) == 0

        if blink_on:
            x = focused_plane["_radar_x"]
            y = focused_plane["_radar_y"]
            color = focused_plane["_radar_color"]

            # 4x4 focused-aircraft marker:
            # X..X
            # .XX.
            # .XX.
            # X..X
            #
            # The ADS-B point sits approximately in the middle.
            x0 = x - 1
            y0 = y - 1

            marker_pixels = [
                (0, 0), (3, 0),
                (1, 1), (2, 1),
                (1, 2), (2, 2),
                (0, 3), (3, 3),
            ]

            for dx, dy in marker_pixels:
                set_pixel(buf, x0 + dx, y0 + dy, color)

    # --------------------------------------------------------
    # Right-side information column
    # --------------------------------------------------------

    now_text = datetime.now(WARSAW_TZ).strftime("%H:%M")
    draw_text(buf, now_text, 68, 3, WHITE)

    # Focused callsign / flight number.
    if focused_plane is not None:
        flight_text = (
            focused_plane.get("callsign")
            or focused_plane.get("registration")
            or "UNKNOWN"
        ).upper()

        flight_color = focused_plane["_radar_color"]
        draw_text(
            buf,
            flight_text[:9],
            68,
            17,
            flight_color
        )
    else:
        draw_text(buf, "NO AC", 68, 13, GRAY)

    # y=23 intentionally left empty:
    # one full 5x7 text row of visual separation before weather.

    temp = weather.get("temp_c")
    if temp is None:
        temp_text = "--°C"
    else:
        temp_text = f"{int(round(temp))}°C"

    draw_text(buf, temp_text[:8], 68, 33, WHITE)

    # Tiny METAR-derived weather icon next to temperature.
    condition = (
        weather.get("condition")
        or weather_condition_from_metar(weather.get("raw_metar", ""))
    )
    draw_weather_icon(buf, 103, 31, condition)

    wind_dir = weather.get("wind_dir")
    if wind_dir is None:
        wind_dir_text = "---°"
    elif str(wind_dir).upper() == "VRB":
        wind_dir_text = "VRB"
    else:
        try:
            wind_dir_text = f"{int(wind_dir):03d}°"
        except Exception:
            wind_dir_text = "---°"

    wind_speed = weather.get("wind_speed_kt")
    wind_gust = weather.get("wind_gust_kt")

    if wind_speed is None:
        wind_text = f"{wind_dir_text}/--KT"
    elif wind_gust is not None and wind_gust > wind_speed:
        wind_text = f"{wind_dir_text}/{wind_speed}G{wind_gust}KT"
    else:
        wind_text = f"{wind_dir_text}/{wind_speed}KT"

    # Compact aviation style, e.g. 210°/4KT.
    draw_text(buf, wind_text[:10], 68, 43, ORANGE)

    draw_text(buf, f"{int(round(range_nm))}NM", 68, 53, GRAY)

    if focused_plane is not None:
        counter = f"{focused_index + 1}/{len(visible_planes)}"
        draw_text(buf, counter[:5], 98, 53, GRAY)
    else:
        draw_text(buf, "0/0", 98, 53, GRAY)

    # 1-pixel Poznan-Lawica mosaic border around the whole radar screen.
    # Drawn last so the frame always stays visible.
    draw_poz_mosaic_frame(buf, block_len=4)

    return buf


# ============================================================
# RENDERERS
# ============================================================

def airline_color(icao):
    return {
        "RYR": YELLOW,
        "LOT": BLUE,
        "WZZ": (255, 60, 180),
        "UAE": RED,
        "QTR": (145, 70, 220),
        "DLH": YELLOW,
        "KLM": CYAN
    }.get((icao or "").upper(), CYAN)


def render_message(title, line1="", line2="", accent=CYAN):
    buf = make_buffer()
    draw_hline(buf, 0, 127, 0, accent)
    draw_hline(buf, 0, 127, 1, accent)
    draw_centered(buf, title[:20], 10, WHITE)
    if line1:
        draw_centered(buf, line1[:20], 28, GRAY)
    if line2:
        draw_centered(buf, line2[:20], 43, GRAY)
    return buf


def render_aircraft(plane):
    buf = make_buffer()

    icao = plane.get("icao") or airline_icao_from_callsign(
        plane.get("callsign", "")
    )
    accent = airline_color(icao)
    top_accent = dominant_logo_color(icao, accent)

    # Upper two lines use the dominant logo color.
    draw_hline(buf, 0, 127, 0, top_accent)
    draw_hline(buf, 0, 127, 1, top_accent)

    # No logo file = empty logo area.
    draw_airline_logo(
        buf, icao,
        3, 4, 34, 27,
        top_accent
    )

    callsign = plane.get("callsign") or "UNKNOWN"
    display_call = callsign[:10]
    draw_text(buf, display_call, 39, 6, WHITE, scale=2, spacing=1)

    airline = (plane.get("airline") or icao or "").upper()
    draw_text(buf, airline[:14], 39, 21, GRAY)

    origin = plane.get("origin") or "???"
    dest = plane.get("destination") or "???"

    # Airport codes in white.
    draw_text(buf, origin[:3], 7, 29, WHITE, scale=2, spacing=1)

    right = dest[:3]
    right_width = text_width(right, scale=2, spacing=1)
    draw_text(
        buf,
        right,
        121 - right_width,
        29,
        WHITE,
        scale=2,
        spacing=1
    )

    draw_hline(buf, 46, 81, 35, top_accent)
    set_pixel(buf, 81, 35, top_accent)
    set_pixel(buf, 80, 34, top_accent)
    set_pixel(buf, 80, 36, top_accent)
    draw_arrow_right(buf, 60, 33, WHITE)

    draw_hline(buf, 2, 125, 44, GRAY)

    aircraft = (plane.get("aircraft") or "----")[:4]
    reg = (plane.get("registration") or "")[:8]

    # First lower row.
    draw_text(buf, aircraft, 3, 46, GREEN)

    # Registration begins exactly at the same x as distance below.
    if reg:
        draw_text(buf, reg, 39, 46, WHITE)

    # Altitude always right-aligned to x=125.
    alt_text = fmt_alt(plane.get("alt"))[:9]
    alt_width = text_width(alt_text)

    vs = plane.get("vertical_speed")

    try:
        vs = float(vs) if vs is not None else 0.0
    except Exception:
        vs = 0.0

    if vs < -100:
        alt_color = RED
    elif vs > 100:
        alt_color = GREEN
    else:
        alt_color = CYAN

    draw_text(
        buf,
        alt_text,
        126 - alt_width,
        46,
        alt_color
    )
    # y=53 intentionally blank.

    # Second lower row.
    draw_text(buf, fmt_speed(plane.get("speed"))[:6], 3, 54, WHITE)

    distance_text = fmt_distance(plane.get("distance_km"))[:7]
    draw_text(
        buf,
        distance_text,
        39,
        54,
        GRAY
    )

    # HDG always right-aligned to the same edge as altitude.
    hdg_text = "HDG" + fmt_heading(plane.get("heading"))
    hdg_width = text_width(hdg_text)
    draw_text(
        buf,
        hdg_text,
        126 - hdg_width,
        54,
        GRAY
    )

    return buf

def render_board(title, rows, accent, arrivals):
    buf = make_buffer()

    # Poznan Lawica mosaic styling.
    draw_poz_mosaic_line(buf, 0, block_w=4, offset=0)
    draw_poz_mosaic_line(buf, 1, block_w=4, offset=2)

    draw_centered(buf, title, 4, WHITE)
    draw_hline(buf, 2, 125, 12, GRAY)

    draw_text(buf, "TIME", 2, 14, GRAY, spacing=0)
    draw_text(buf, "FROM" if arrivals else "TO", 33, 14, GRAY, spacing=0)
    draw_text(buf, "FLIGHT", 58, 14, GRAY, spacing=0)
    draw_text(buf, "STATUS", 93, 14, GRAY, spacing=0)

    draw_hline(buf, 2, 125, 22, GRAY)

    if not rows:
        draw_centered(buf, "NO LIVE DATA", 36, ORANGE)
        draw_poz_mosaic_line(buf, 63, block_w=4, offset=1)
        return buf

    y_positions = [25, 34, 43, 52]

    for i, row in enumerate(rows[:4]):
        y = y_positions[i]

        draw_text(buf, row.get("time", "--:--")[:5], 2, y, WHITE, spacing=0)
        draw_text(buf, row.get("airport", "???")[:3], 35, y, CYAN, spacing=1)
        draw_text(buf, normalize_flight_number(row.get("flight"))[:6], 57, y, WHITE, spacing=0)

        status = compact_status(row, arrivals)

        status_color = GREEN
        if status in {"CANCEL", "DELAY"}:
            status_color = RED
        elif status.startswith("G") or status == "BOARD":
            status_color = YELLOW
        elif ":" in status:
            status_color = ORANGE

        draw_text(buf, status[:6], 91, y, status_color, spacing=0)

    draw_poz_mosaic_line(buf, 63, block_w=4, offset=1)
    return buf

def draw_matrix(screen, buf, show_grid):
    screen.fill(BG)

    for y in range(MATRIX_H):
        for x in range(MATRIX_W):
            color = (
                buf[y][x]
                if buf[y][x] is not None
                else LED_OFF
            )

            px = x * SCALE
            py = y * SCALE

            if show_grid:
                margin = 1
                pygame.draw.rect(
                    screen,
                    color,
                    (
                        px + margin,
                        py + margin,
                        SCALE - 2 * margin,
                        SCALE - 2 * margin
                    ),
                    border_radius=1
                )
            else:
                pygame.draw.rect(
                    screen,
                    color,
                    (px, py, SCALE, SCALE)
                )



# ============================================================
# HUB75 OUTPUT
# ============================================================

def monotonic_ms():
    """Monotonic clock shared by emulator and headless matrix mode."""
    return int(time.monotonic() * 1000)


def create_hub75_matrix(args):
    """Create the physical HUB75 output only when --matrix is requested."""
    try:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
    except ImportError as exc:
        raise RuntimeError(
            "rgbmatrix is not installed in this Python environment. "
            "Install rpi-rgb-led-matrix into the FlightWall .venv first."
        ) from exc

    cfg = CONFIG.get("matrix", {})
    options = RGBMatrixOptions()
    options.rows = int(args.matrix_rows or cfg.get("rows", 64))
    options.cols = int(args.matrix_cols or cfg.get("cols", 128))
    options.chain_length = int(args.matrix_chain or cfg.get("chain_length", 1))
    options.parallel = int(args.matrix_parallel or cfg.get("parallel", 1))
    options.hardware_mapping = str(
        args.gpio_mapping or cfg.get("hardware_mapping", "regular")
    )
    options.gpio_slowdown = int(
        args.gpio_slowdown
        if args.gpio_slowdown is not None
        else cfg.get("gpio_slowdown", 4)
    )
    options.brightness = max(
        1,
        min(
            100,
            int(
                args.brightness
                if args.brightness is not None
                else cfg.get("brightness", 35)
            )
        )
    )

    # FlightWall writes cache/debug files after matrix initialization.
    # Keep the service's root privileges instead of allowing the library to
    # drop to the daemon user, otherwise those writes can fail.
    options.drop_privileges = False

    matrix = RGBMatrix(options=options)

    print(
        "[MATRIX] initialized:",
        f"{matrix.width}x{matrix.height}",
        f"mapping={options.hardware_mapping}",
        f"slowdown={options.gpio_slowdown}",
        f"brightness={options.brightness}%",
        flush=True
    )

    if matrix.width != MATRIX_W or matrix.height != MATRIX_H:
        matrix.Clear()
        raise RuntimeError(
            f"Matrix geometry is {matrix.width}x{matrix.height}, but FlightWall "
            f"renders {MATRIX_W}x{MATRIX_H}. Check rows/cols/chain/parallel."
        )

    return matrix, matrix.CreateFrameCanvas()


def buffer_to_pil(buf):
    """Convert the 128x64 logical framebuffer to an RGB Pillow image."""
    image = Image.new("RGB", (MATRIX_W, MATRIX_H), (0, 0, 0))
    pixels = []
    for y in range(MATRIX_H):
        for x in range(MATRIX_W):
            # None means LED physically OFF. Do not use emulator LED_OFF gray.
            pixels.append(buf[y][x] if buf[y][x] is not None else (0, 0, 0))
    image.putdata(pixels)
    return image


def draw_hub75(matrix, canvas, buf):
    """Copy one FlightWall framebuffer to the physical matrix, vsync-safe."""
    canvas.SetImage(buffer_to_pil(buf))
    return matrix.SwapOnVSync(canvas)


def matrix_test_frame(kind):
    """Create simple full-panel test frames without network access."""
    buf = make_buffer()

    if kind == "red":
        color = (255, 0, 0)
        for y in range(MATRIX_H):
            for x in range(MATRIX_W):
                set_pixel(buf, x, y, color)
        return buf

    if kind == "green":
        color = (0, 255, 0)
        for y in range(MATRIX_H):
            for x in range(MATRIX_W):
                set_pixel(buf, x, y, color)
        return buf

    if kind == "blue":
        color = (0, 0, 255)
        for y in range(MATRIX_H):
            for x in range(MATRIX_W):
                set_pixel(buf, x, y, color)
        return buf

    if kind == "white":
        color = (255, 255, 255)
        for y in range(MATRIX_H):
            for x in range(MATRIX_W):
                set_pixel(buf, x, y, color)
        return buf

    # Geometry/orientation frame: border, centre cross and corner labels.
    draw_box(buf, 0, 0, MATRIX_W - 1, MATRIX_H - 1, WHITE)
    draw_vline(buf, 0, MATRIX_H - 1, MATRIX_W // 2, (70, 70, 70))
    draw_hline(buf, 0, MATRIX_W - 1, MATRIX_H // 2, (70, 70, 70))
    draw_text(buf, "TL", 3, 3, RED)
    draw_text(buf, "TR", 111, 3, GREEN)
    draw_text(buf, "BL", 3, 54, BLUE)
    draw_text(buf, "BR", 111, 54, YELLOW)
    draw_centered(buf, "128X64", 27, CYAN)
    return buf


def run_matrix_test(matrix, canvas):
    """Cycle primary colours then leave a geometry test visible."""
    sequence = (
        ("RED", "red", 1.5),
        ("GREEN", "green", 1.5),
        ("BLUE", "blue", 1.5),
        ("WHITE", "white", 1.5),
        ("GEOMETRY", "geometry", None),
    )

    try:
        for label, kind, seconds in sequence:
            print(f"[MATRIX TEST] {label}", flush=True)
            canvas = draw_hub75(matrix, canvas, matrix_test_frame(kind))
            if seconds is not None:
                time.sleep(seconds)
            else:
                print("[MATRIX TEST] CTRL+C to exit.", flush=True)
                while True:
                    time.sleep(1)
    finally:
        matrix.Clear()


# ============================================================
# SCREEN CYCLE
# ============================================================

def next_screen(screen_name):
    order = ["aircraft", "arrivals", "departures"]
    idx = order.index(screen_name)
    return order[(idx + 1) % len(order)]


def screen_duration(screen_name):
    s = CONFIG["screens"]
    if screen_name == "aircraft":
        return int(s["aircraft_seconds"])
    if screen_name == "arrivals":
        return int(s["arrivals_seconds"])
    return int(s["departures_seconds"])


# ============================================================
# DEMO DATA
# ============================================================

DEMO_PLANES = [
    {
        "callsign": "RYR2336",
        "icao": "RYR",
        "airline": "RYANAIR",
        "origin": "POZ",
        "destination": "STN",
        "aircraft": "B38M",
        "registration": "SP-RZA",
        "alt": 18400,
        "speed": 312,
        "distance_km": 14.8,
        "heading": 284,
        "vertical_speed": -900,
        "lat": 52.46,
        "lon": 16.70
    },
    {
        "callsign": "LOT3947",
        "icao": "LOT",
        "airline": "LOT",
        "origin": "WAW",
        "destination": "POZ",
        "aircraft": "E195",
        "registration": "SP-LNN",
        "alt": 7200,
        "speed": 246,
        "distance_km": 9.6,
        "heading": 276,
        "vertical_speed": 1200,
        "lat": 52.40,
        "lon": 16.73
    }
]

DEMO_ARRIVALS = [
    {"time": "18:35", "airport": "WAW", "flight": "LO3947", "status": "Landed", "gate": ""},
    {"time": "19:05", "airport": "STN", "flight": "FR2336", "status": "19:02", "gate": ""},
    {"time": "19:20", "airport": "LTN", "flight": "W61305", "status": "19:18", "gate": ""},
    {"time": "19:45", "airport": "FRA", "flight": "LH1380", "status": "19:47", "gate": ""},
]

DEMO_DEPARTURES = [
    {"time": "19:10", "airport": "STN", "flight": "FR2337", "status": "Boarding", "gate": "7"},
    {"time": "19:40", "airport": "WAW", "flight": "LO3948", "status": "", "gate": "4"},
    {"time": "20:05", "airport": "LTN", "flight": "W61306", "status": "", "gate": "5"},
    {"time": "20:25", "airport": "FRA", "flight": "LH1381", "status": "", "gate": "3"},
]

DEMO_WEATHER = {
    "station": "EPPO",
    "temp_c": 18,
    "wind_dir": 250,
    "wind_speed_kt": 12,
    "wind_gust_kt": 20,
    "raw_metar": "EPPO DEMO 25012G20KT 9999 FEW030 18/11 Q1017",
    "condition": "partly_cloudy"
}


# ============================================================
# MAIN
# ============================================================

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOGO_DIR.mkdir(parents=True, exist_ok=True)

    # Always create missing-logo storage immediately.
    if not MISSING_LOGOS_PATH.exists():
        MISSING_LOGOS_PATH.write_text("{}\n", encoding="utf-8")

    # This file is created BEFORE any network request/thread.
    # If it does not exist, this exact v0.7 file is not being executed.
    AIRPORT_DEBUG_PATH.write_text(
        "FlightWall LIVE v0.25 started\n"
        f"Script: {Path(__file__).resolve()}\n"
        f"Time: {datetime.now(WARSAW_TZ).isoformat()}\n",
        encoding="utf-8"
    )

    print("=" * 60, flush=True)
    print("FlightWall LIVE v0.25", flush=True)
    print(f"Running: {Path(__file__).resolve()}", flush=True)
    print(f"Debug:   {AIRPORT_DEBUG_PATH}", flush=True)
    print(f"Missing: {MISSING_LOGOS_PATH}", flush=True)
    print(f"ADSB refresh: {CONFIG['refresh']['adsb_seconds']}s + automatic 429 backoff", flush=True)
    print("=" * 60, flush=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use fake data instead of internet sources."
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Render to the physical HUB75 matrix instead of a pygame window."
    )
    parser.add_argument(
        "--matrix-test",
        action="store_true",
        help="Run the physical HUB75 colour/geometry test and exit on Ctrl+C."
    )
    parser.add_argument("--brightness", type=int, metavar="1-100")
    parser.add_argument("--gpio-slowdown", type=int, metavar="N")
    parser.add_argument("--gpio-mapping", metavar="NAME")
    parser.add_argument("--matrix-rows", type=int, metavar="N")
    parser.add_argument("--matrix-cols", type=int, metavar="N")
    parser.add_argument("--matrix-chain", type=int, metavar="N")
    parser.add_argument("--matrix-parallel", type=int, metavar="N")
    parser.add_argument(
        "--test-airport",
        action="store_true",
        help="Fetch POZ board, print results, then exit."
    )
    parser.add_argument(
        "--test-adsb",
        action="store_true",
        help="Fetch nearby ADS-B aircraft once, print them, then exit."
    )
    parser.add_argument(
        "--simulate-callsign",
        metavar="CALLSIGN",
        help=(
            "Pretend ADS-B returned this callsign, force HexDB to be empty, "
            "and test the POZ-board fallback."
        )
    )
    parser.add_argument(
        "--simulate-direction",
        choices=("any", "arrival", "departure"),
        default="any",
        help="Limit simulation candidates to arrivals or departures."
    )
    parser.add_argument(
        "--simulate-vs",
        type=float,
        default=0.0,
        metavar="FPM",
        help="Vertical speed: negative=arrival, positive=departure."
    )
    args = parser.parse_args()

    if args.test_adsb:
        print("[TEST] Running ADS-B test only...", flush=True)
        try:
            planes = fetch_nearby_aircraft()
            print(f"[TEST] aircraft={len(planes)}", flush=True)
            for p in planes:
                print(
                    p.get("callsign"),
                    p.get("registration"),
                    p.get("origin"),
                    "->",
                    p.get("destination"),
                    flush=True
                )
        except Exception as exc:
            print(
                f"[ADSB TEST ERROR] {type(exc).__name__}: {exc}",
                flush=True
            )
            raise
        return

    if args.test_airport:
        print("[TEST] Running airport-board test only...", flush=True)
        board = fetch_airport_board()
        print("\nARRIVALS:", flush=True)
        for row in board.get("arrivals", []):
            print(row, flush=True)
        print("\nDEPARTURES:", flush=True)
        for row in board.get("departures", []):
            print(row, flush=True)
        print(f"\nDebug saved to: {AIRPORT_DEBUG_PATH}", flush=True)
        return

    if args.simulate_callsign:
        callsign = clean_callsign(args.simulate_callsign)
        print(
            f"[SIMULATION] ADS-B callsign={callsign}; "
            f"VS={args.simulate_vs:+.0f} ft/min; "
            "HexDB forced EMPTY",
            flush=True
        )
        print("[SIMULATION] Fetching full official POZ board...", flush=True)
        fetch_airport_board()

        result = route_from_poz_board(
            callsign,
            args.simulate_vs
        )
        if result:
            print(
                "[SIMULATION RESULT] MATCH:",
                f"{result.get('origin')} -> {result.get('destination')}",
                f"via {result.get('flight')}",
                f"({result.get('match')})",
                flush=True
            )
        else:
            print(
                "[SIMULATION RESULT] NO SAFE EXACT MATCH -> ??? -> ???",
                flush=True
            )

            candidates = poz_candidates_for_callsign(
                callsign,
                args.simulate_direction
            )

            if candidates:
                print(
                    f"[SIMULATION] Same-airline POZ candidates "
                    f"({args.simulate_direction}):",
                    flush=True
                )
                for item in candidates:
                    print(
                        f"  {item.get('time','--:--')} "
                        f"{item.get('flight','?')} "
                        f"{item.get('origin','???')} -> "
                        f"{item.get('destination','???')} "
                        f"[{item.get('direction','?')}]",
                        flush=True
                    )
            else:
                print(
                    "[SIMULATION] No same-airline POZ candidates found.",
                    flush=True
                )

        return

    # Physical matrix mode is fully headless; pygame display/event handling is
    # only initialized for the desktop emulator.
    matrix_mode = bool(args.matrix or args.matrix_test)
    screen = None
    clock = None
    hub75 = None
    hub75_canvas = None

    if matrix_mode:
        hub75, hub75_canvas = create_hub75_matrix(args)
        if args.matrix_test:
            run_matrix_test(hub75, hub75_canvas)
            return
    else:
        pygame.init()
        pygame.display.set_caption("FlightWall LIVE v0.25 - 128x64")
        screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        clock = pygame.time.Clock()

    show_grid = bool(CONFIG["display"]["show_grid"])
    current_screen = "aircraft"
    screen_started = monotonic_ms()
    aircraft_item_started = screen_started
    aircraft_index = 0

    # Radar is an overlay screen shown independently of the normal cycle.
    last_radar_ms = monotonic_ms()
    return_screen_after_radar = "aircraft"

    state = None
    workers = []

    if not args.demo:
        state = LiveState()

        # First POZ fetch runs on the MAIN THREAD.
        # This guarantees immediate console output and diagnostics.
        print("[STARTUP] Fetching POZ airport board...", flush=True)
        try:
            first_board = fetch_airport_board()
            with state.lock:
                state.arrivals = first_board.get("arrivals", [])
                state.departures = first_board.get("departures", [])
                state.airport_error = "; ".join(first_board.get("errors", []))
                state.airport_updated = datetime.now(WARSAW_TZ)

            print(
                "[STARTUP] POZ board ready:",
                f"arrivals={len(state.arrivals)}",
                f"departures={len(state.departures)}",
                flush=True
            )
        except Exception as exc:
            startup_error = f"{type(exc).__name__}: {exc}"
            with state.lock:
                state.airport_error = startup_error

            with AIRPORT_DEBUG_PATH.open("a", encoding="utf-8") as f:
                f.write(f"STARTUP AIRPORT ERROR: {startup_error}\n")

            print(
                f"[STARTUP] POZ board ERROR: {startup_error}",
                flush=True
            )

        t1 = threading.Thread(
            target=adsb_worker,
            args=(state,),
            daemon=True
        )
        t2 = threading.Thread(
            target=airport_worker,
            args=(state,),
            daemon=True
        )
        t3 = threading.Thread(
            target=weather_worker,
            args=(state,),
            daemon=True
        )

        t1.start()
        t2.start()
        t3.start()
        workers = [t1, t2, t3]

    running = True

    try:
        while running:
            now_ms = monotonic_ms()

            radar_every_ms = int(
                CONFIG["radar"]["show_every_seconds"]
            ) * 1000

            # Independent radar/weather overlay every 3 minutes.
            # The radar's exit time is decided later, after we know how many
            # aircraft are actually visible inside 40 NM.
            if (
                current_screen != "radar"
                and (now_ms - last_radar_ms) >= radar_every_ms
            ):
                return_screen_after_radar = current_screen
                current_screen = "radar"
                screen_started = now_ms
                last_radar_ms = now_ms

            # Normal cycle remains:
            #   aircraft -> arrivals -> departures
            elif (
                current_screen != "radar"
                and (now_ms - screen_started) / 1000.0
                >= screen_duration(current_screen)
            ):
                current_screen = next_screen(current_screen)
                screen_started = now_ms

                if current_screen == "aircraft":
                    # A fresh aircraft block starts from the nearest aircraft.
                    aircraft_index = 0
                    aircraft_item_started = now_ms

            # While the aircraft screen is active, rotate aircraft every 5 s.
            if current_screen == "aircraft":
                rotate_seconds = float(
                    CONFIG["screens"].get("aircraft_rotate_seconds", 5)
                )
                if (
                    (now_ms - aircraft_item_started) / 1000.0
                    >= rotate_seconds
                ):
                    aircraft_index += 1
                    aircraft_item_started = now_ms

            if not matrix_mode:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False

                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False

                        elif event.key == pygame.K_a:
                            current_screen = "aircraft"
                            screen_started = now_ms
                            aircraft_item_started = now_ms
                            aircraft_index = 0

                        elif event.key == pygame.K_r:
                            current_screen = "arrivals"
                            screen_started = now_ms

                        elif event.key == pygame.K_d:
                            current_screen = "departures"
                            screen_started = now_ms

                        elif event.key == pygame.K_SPACE:
                            if current_screen == "radar":
                                current_screen = return_screen_after_radar
                                screen_started = now_ms
                            else:
                                current_screen = next_screen(current_screen)
                                screen_started = now_ms
                                if current_screen == "aircraft":
                                    aircraft_index = 0
                                    aircraft_item_started = now_ms

                        elif event.key == pygame.K_m:
                            if current_screen != "radar":
                                return_screen_after_radar = current_screen
                            current_screen = "radar"
                            screen_started = now_ms
                            last_radar_ms = now_ms

                        elif event.key == pygame.K_n:
                            # Manual next aircraft without restarting the 60 s block.
                            if current_screen != "aircraft":
                                current_screen = "aircraft"
                                screen_started = now_ms
                            aircraft_index += 1
                            aircraft_item_started = now_ms

                        elif event.key == pygame.K_g:
                            show_grid = not show_grid

                        elif event.key == pygame.K_f and state:
                            state.force_adsb.set()
                            state.force_airport.set()
                            state.force_weather.set()

            if args.demo:
                snap = {
                    "aircraft": DEMO_PLANES,
                    "arrivals": DEMO_ARRIVALS,
                    "departures": DEMO_DEPARTURES,
                    "weather": DEMO_WEATHER,
                    "aircraft_error": "",
                    "airport_error": "",
                    "weather_error": ""
                }
            else:
                snap = state.snapshot()

            # Radar remains on screen until EVERY currently visible aircraft
            # has received one complete focus slot.
            if current_screen == "radar":
                visible_count = len(
                    radar_visible_planes(snap.get("aircraft", []))
                )
                focus_slot_ms = max(
                    500,
                    int(float(
                        CONFIG["radar"].get("focus_seconds", 3)
                    ) * 1000)
                )

                # With no aircraft, keep the radar for one focus slot so the
                # weather/map screen is still visible briefly.
                radar_required_ms = max(1, visible_count) * focus_slot_ms

                if (now_ms - screen_started) >= radar_required_ms:
                    current_screen = return_screen_after_radar
                    screen_started = now_ms

                    if current_screen == "aircraft":
                        aircraft_item_started = now_ms

            if current_screen == "aircraft":
                planes = snap["aircraft"]

                if planes:
                    aircraft_index %= len(planes)
                    frame = render_aircraft(
                        planes[aircraft_index]
                    )
                else:
                    message = (
                        "WAITING FOR ADSB"
                        if not snap["aircraft_error"]
                        else "ADSB ERROR"
                    )
                    frame = render_message(
                        message,
                        "CHECK INTERNET" if snap["aircraft_error"] else "LOADING...",
                        CONFIG["location"]["name"],
                        RED if snap["aircraft_error"] else CYAN
                    )

            elif current_screen == "arrivals":
                frame = render_board(
                    "POZ ARRIVALS",
                    snap["arrivals"],
                    GREEN,
                    arrivals=True
                )

            elif current_screen == "departures":
                frame = render_board(
                    "POZ DEPARTURES",
                    snap["departures"],
                    YELLOW,
                    arrivals=False
                )

            else:
                frame = render_radar(
                    snap["aircraft"],
                    snap.get("weather", {}),
                    radar_elapsed_ms=(now_ms - screen_started)
                )

            if matrix_mode:
                hub75_canvas = draw_hub75(hub75, hub75_canvas, frame)
                matrix_fps = max(1, int(CONFIG.get("matrix", {}).get("fps", 20)))
                time.sleep(1.0 / matrix_fps)
            else:
                draw_matrix(screen, frame, show_grid)
                pygame.display.flip()
                clock.tick(FPS)

    finally:
        if state:
            state.stop_event.set()
            state.force_adsb.set()
            state.force_airport.set()
            state.force_weather.set()

        if hub75 is not None:
            hub75.Clear()
        if not matrix_mode:
            pygame.quit()


if __name__ == "__main__":
    main()
