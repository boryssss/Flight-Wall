AIRLINE_DISPLAY_NAMES = {
    "RYR": "RYANAIR",
    "RYS": "BUZZ BY RYANAIR",
    "MAY": "MALTA AIR BY RYANAIR",
    "LDA": "LAUDA BY RYANAIR",
    "LOT": "LOT POLISH AIRLINES",
    "WZZ": "WIZZ AIR",
    "WMT": "WIZZ AIR",
    "WUK": "WIZZ AIR",
    "KLM": "KLM",
    "DLH": "LUFTHANSA",
    "SAS": "SAS - Scandinavian Airlines",
    "AUA": "AUSTRIAN",
    "SWR": "SWISS",
    "AFR": "AIR FRANCE",
    "BAW": "BRITISH AIRWAYS",
    "EZY": "EASYJET",
    "EWG": "EUROWINGS",
    "ENT": "ENTER AIR",
    "QTR": "QATAR AIRWAYS",
    "UAE": "EMIRATES",
    "BRX": "BRAATHENS FOR SAS",
}

def display_airline_name(plane):
    """Return a consistent airline name for the FlightWall UI."""
    icao = (plane.get("icao") or "").upper().strip()
    airline = (plane.get("airline") or "").upper().strip()

    if icao in AIRLINE_DISPLAY_NAMES:
        return AIRLINE_DISPLAY_NAMES[icao]

    return airline or icao
