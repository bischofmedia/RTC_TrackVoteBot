import os
import re
from functools import lru_cache
import sheets

# Kontinent-Mapping aus ENV
def _parse_codes(env_key: str) -> set[int]:
    raw = os.getenv(env_key, "")
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return result


CONTINENT_CODES = {
    "europa": _parse_codes("EUROPA_CODES"),
    "amerika": _parse_codes("AMERIKA_CODES"),
    "asien": _parse_codes("ASIEN_CODES"),
}


@lru_cache(maxsize=1)
def _load_all_tracks() -> list[dict]:
    """Lädt alle Strecken aus dem Sheet (gecacht)."""
    return sheets.get_tracks_from_sheet()


def invalidate_cache():
    """Cache leeren, z.B. nach Sheet-Änderungen."""
    _load_all_tracks.cache_clear()


def get_tracks_by_continent(continent: str) -> list[str]:
    """Gibt die einzigartigen Streckennamen (ohne Variante) eines Kontinents zurück."""
    codes = CONTINENT_CODES.get(continent.lower(), set())
    all_tracks = _load_all_tracks()

    seen = set()
    result = []
    for t in all_tracks:
        if t["code"] in codes:
            base = _extract_base_name(t["name"])
            if base not in seen:
                seen.add(base)
                result.append(base)
    return sorted(result)


def get_variants(base_name: str) -> list[str]:
    """Gibt alle Vollnamen (inkl. Variante) für eine Basisstrecke zurück."""
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
    # Bekannte Mehrwort-Basisnamen die NICHT getrennt werden sollen
    # (d.h. der ' - ' gehört zum Basis-Namen)
    no_split = [
        "Autopolis IRC",
        "Kyoto DP",
        "Lago Maggiore",
        "Blue Moon Bay",
        "Dragon Trail",
        "Grand Valley",
        "Sainte-Croix",
        "Sardegna",
        "Tokyo Expressway",
        "Watkins Glen",
        "Willow Springs",
        "Red Bull Ring",
        "Brands Hatch",
        "LeMans",
        "Nürburgring",
        "Broad Bean Raceway",
        "Alsace",
        "Barcelona",
        "Daytona",
        "Deep Forest Raceway",
        "Fuji",
        "Suzuka",
        "Mount Panorama",
        "Special Stage Route X",
        "Trial Mountain",
        "High Speed Ring",
        "Circuit Gilles Villeneuve",
        "Yas Marina Circuit",
        "Spa-Francorchamps",
        "Laguna Seca",
        "Goodwood Motor Circuit",
        "Tsukuba Circuit",
        "Northern Isle Speedway",
        "Road Atlanta",
        "Autódromo De Interlagos",
    ]

    for base in no_split:
        if full_name.startswith(base):
            return base

    # Fallback: alles vor ' - ' nehmen
    if " - " in full_name:
        return full_name.split(" - ")[0].strip()

    # Klammern entfernen
    name = re.sub(r"\s*\(.*\)", "", full_name).strip()
    return name
