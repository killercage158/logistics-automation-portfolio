"""Step 1: turn what staff typed into one clean request.

Staff type ports and containers in many ways ("HPH", "Hải Phòng", "40 HQ").
Everything downstream uses ONE spelling, so we normalise once, here.
An unknown value is an error with a helpful message, never a silent guess.

WHY: every later step compares ports and containers as plain strings. If one
file says "HPH" and another says "Haiphong", a plain string compare silently
finds nothing. One alias table at the front door prevents that whole class of
bug.

In production, the lane (POL, POD, container, cargo type) is read from the row
staff ticked, and port-name matching also handles alternative port codes. Simplified here: 7 ports instead of ~100, no port codes.
"""
import re
import unicodedata
from dataclasses import dataclass

# canonical name -> spellings people use (written in the simple "key" form below)
PORT_ALIASES = {
    "Hai Phong": ["haiphong", "hph", "vnhph", "haiphongport"],
    "Ho Chi Minh": ["hochiminh", "hcm", "hcmc", "saigon", "sgn", "vnsgn", "catlai", "hochiminhcity"],
    "Da Nang": ["danang", "dad", "vndad", "tiensa"],
    "Singapore": ["singapore", "sin", "sgsin"],
    "Busan": ["busan", "pusan", "bus", "krpus"],
    "Los Angeles": ["losangeles", "la", "lax", "uslax"],
    "Rotterdam": ["rotterdam", "rtm", "nlrtm"],
}
# Ports in the USA / Europe also pay an advance-manifest (AMS) fee.
US_EU_PORTS = {"Los Angeles", "Rotterdam"}

# Inland places for trucking. The list is OPEN: an unknown place is kept as typed
# (see normalise_place) because staff must never be blocked by a hard-coded list.
PLACE_ALIASES = {
    "Bac Ninh": ["bacninh"], "Ha Noi": ["hanoi"], "Hai Duong": ["haiduong"],
    "Hai Phong": PORT_ALIASES["Hai Phong"], "Ho Chi Minh": PORT_ALIASES["Ho Chi Minh"],
    "Binh Duong": ["binhduong"], "Long An": ["longan"], "Da Nang": PORT_ALIASES["Da Nang"],
}

CONTAINER_ALIASES = {
    "20GP": ["20gp", "20", "20ft", "20dc", "20std", "20feet"],
    "40GP": ["40gp", "40", "40ft", "40dc", "40std", "40feet"],
    "40HC": ["40hc", "40hq", "40highcube", "40hcdc"],
}
CARGO_ALIASES = {
    "general": ["general", "gen", "gc", "generalcargo", "dry", "normal"],
    "charcoal": ["charcoal", "than", "thancui", "coalcharcoal"],
}


def key(text):
    """The "simple form" of a word, used for every comparison in this file.

    Lower-case, remove accents, spaces and punctuation: 'Hải Phòng' -> 'haiphong'."""
    text = str(text).lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text)


def _lookup(text, table, what):
    wanted = key(text)
    for canonical, aliases in table.items():
        if wanted == key(canonical) or wanted in aliases:
            return canonical
    raise ValueError(f"Unknown {what} '{text}'. Known: {', '.join(table)}")


def normalise_port(text):
    return _lookup(text, PORT_ALIASES, "port")


def normalise_place(text):
    """Inland place for trucking. Unknown places are kept (title-cased), not rejected."""
    try:
        return _lookup(text, PLACE_ALIASES, "place")
    except ValueError:
        return " ".join(w.capitalize() for w in str(text).split())


def place_in_text(place, text):
    """True if any spelling of `place` appears inside `text`."""
    haystack = key(text)
    spellings = [key(place)] + [a for a in PLACE_ALIASES.get(place, []) if len(a) >= 3]
    return any(s in haystack for s in spellings)


def normalise_container(text):
    return _lookup(text, CONTAINER_ALIASES, "container")


def normalise_cargo(text):
    return _lookup(text, CARGO_ALIASES, "cargo type")


def port_in_text(port, text):
    """True if any spelling of `port` appears inside `text` (used to check a cited row)."""
    haystack = key(text)
    spellings = [key(port)] + [a for a in PORT_ALIASES[port] if len(a) >= 3]
    return any(s in haystack for s in spellings)


@dataclass(frozen=True)
class Request:
    pol: str
    pod: str
    container: str
    cargo: str
    qty: int = 1                 # number of containers

    @property
    def region(self):
        return "us_eu" if self.pod in US_EU_PORTS else "asia"

    def label(self):
        qty = f"{self.qty} x " if self.qty != 1 else ""
        return f"{self.pol} -> {self.pod} | {qty}{self.container} | {self.cargo}"


def build_request(pol, pod, container, cargo, qty=1):
    if qty < 1:
        raise ValueError("Quantity must be at least 1.")
    req = Request(normalise_port(pol), normalise_port(pod),
                  normalise_container(container), normalise_cargo(cargo), qty)
    if req.pol == req.pod:
        raise ValueError("Loading port and discharge port are the same.")
    return req
