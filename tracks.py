import os
import re
from functools import lru_cache
import sheets

# Kontinent-Mapping aus ENV
def _parse_codes(env_key: str) -> set[str]:
    raw = os.getenv(env_key, "")
    result = set()
    for part in raw.split(","):
        part = part.strip().upper()
        if part:
            result.add(part)
    return result


CONTINENT_CODES = {
    "europa": _parse_codes("EUROPA_CODES"),
    "amerika": _parse_codes("AMERIKA_CODES"),
    "asien": _parse_codes("ASIEN_CODES"),
}


@lru_cache(maxsize=1)
def _load_all_tracks() -> list[dict]:
    return sheets.get_tracks_from_sheet()


def invalidate_cache():
    _load_all_tracks.cache_clear()


def get_tracks_by_continent(continent: str, exclude_fully_used: set[str] = None) -> list[str]:
    """
    Gibt die einzigartigen Streckennamen (ohne Variante) eines Kontinents zurück.
    Strecken, bei denen ALLE Varianten bereits in exclude_fully_used enthalten sind,
    oder die via "Alle Varianten" gewählt wurden, werden weggelassen.
    """
    codes = CONTINENT_CODES.get(continent.lower(), set())
    all_tracks = _load_all_tracks()
    exclude_fully_used = exclude_fully_used or set()

    # Strecken die via "Alle Varianten" gewählt wurden direkt sperren
    alle_varianten_bases = {
        v.replace(" - Alle Varianten", "").strip()
        for v in exclude_fully_used
        if v.endswith(" - Alle Varianten")
    }

    seen = set()
    result = []
    for t in all_tracks:
        if t["code"] not in codes:
            continue
        base = _extract_base_name(t["name"])
        if base in seen:
            continue
        seen.add(base)

        # Gesperrt via "Alle Varianten"
        if base in alle_varianten_bases:
            continue

        # Prüfen ob alle Varianten dieser Strecke bereits gewählt wurden
        all_variants = [x["name"] for x in all_tracks if _extract_base_name(x["name"]) == base]
        if all_variants and all(v in exclude_fully_used for v in all_variants):
            continue

        result.append(base)
    return sorted(result)


def get_variants(base_name: str) -> list[str]:
    all_tracks = _load_all_tracks()
    result = []
    for t in all_tracks:
        if _extract_base_name(t["name"]) == base_name:
            result.append(t["name"])
    return result


def _extract_base_name(full_name: str) -> str:
    """
    Extrahiert den Basis-Streckennamen aus dem vollen Namen.
    Beispiele:
      'Nürburgring GP/F'          → 'Nürburgring'
      'Lago Maggiore - Center REV' → 'Lago Maggiore'
      'Laguna Seca'                → 'Laguna Seca'
      'Autopolis IRC - Short'      → 'Autopolis IRC'
      'Kyoto DP - Miyabi'          → 'Kyoto DP'
      'Willow Springs (Big Willow)'→ 'Willow Springs'
    """
    no_split = [
        "Autopolis IRC", "Kyoto DP", "Lago Maggiore", "Blue Moon Bay",
        "Dragon Trail", "Grand Valley", "Sainte-Croix", "Sardegna",
        "Tokyo Expressway", "Watkins Glen", "Willow Springs", "Red Bull Ring",
        "Brands Hatch", "LeMans", "Nürburgring", "Broad Bean Raceway",
        "Alsace", "Barcelona", "Daytona", "Deep Forest Raceway", "Fuji",
        "Suzuka", "Mount Panorama", "Special Stage Route X", "Trial Mountain",
        "High Speed Ring", "Circuit Gilles Villeneuve", "Yas Marina Circuit",
        "Spa-Francorchamps", "Laguna Seca", "Goodwood Motor Circuit",
        "Tsukuba Circuit", "Northern Isle Speedway", "Road Atlanta",
        "Autódromo De Interlagos",
    ]

    for base in no_split:
        if full_name.startswith(base):
            return base

    if " - " in full_name:
        return full_name.split(" - ")[0].strip()

    name = re.sub(r"\s*\(.*\)", "", full_name).strip()
    return name
