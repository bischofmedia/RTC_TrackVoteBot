import os
from functools import lru_cache
import db

# Mapping DB-Continent → interne Keys
# Yas Marina ist in DB als 'Asia' aber gehört für RTC zu Europa & Mittlerer Osten
CONTINENT_MAP = {
    "europa":   {"Europe", "Middle East"},
    "amerika":  {"North America", "South America"},
    "asien":    {"Asia", "Oceania"},
}

# Strecken die für Yas Marina eine Ausnahme brauchen:
# In DB steht continent='Asia', soll aber unter 'europa' erscheinen
CONTINENT_OVERRIDES = {
    "Yas Marina Circuit": "europa",
}


@lru_cache(maxsize=1)
def _load_all_tracks() -> tuple[dict, ...]:
    """Lädt alle Strecken aus der DB (gecacht als tuple für lru_cache)."""
    excluded = {t.strip() for t in os.getenv("EXCLUDED_TRACKS", "").split(",") if t.strip()}
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, variant, country_short, continent
                FROM tracks
                ORDER BY name, variant
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for name, variant, country_short, continent in rows:
        full_name = f"{name} - {variant}" if variant else name
        if name in excluded or full_name in excluded:
            continue
        result.append({
            "name": name,
            "variant": variant or "",
            "full_name": full_name,
            "country_short": country_short or "",
            "continent": continent or "",
        })
    return tuple(result)


def invalidate_cache():
    _load_all_tracks.cache_clear()


def _get_continent_key(track: dict) -> str:
    """Gibt den internen Kontinent-Key für eine Strecke zurück."""
    # Ausnahme-Override prüfen
    if track["name"] in CONTINENT_OVERRIDES:
        return CONTINENT_OVERRIDES[track["name"]]
    # Normales Mapping
    db_continent = track["continent"]
    for key, db_values in CONTINENT_MAP.items():
        if db_continent in db_values:
            return key
    return ""


def get_tracks_by_continent(continent: str, exclude_fully_used: set[str] = None) -> list[str]:
    """
    Gibt die einzigartigen Streckennamen eines Kontinents zurück.
    Strecken deren alle Varianten bereits gewählt wurden, werden weggelassen.
    """
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
        if _get_continent_key(t) != continent.lower():
            continue
        name = t["name"]
        if name in seen:
            continue
        seen.add(name)

        if name in alle_varianten_bases:
            continue

        # Alle Varianten dieser Strecke
        all_variants = [x["full_name"] for x in all_tracks if x["name"] == name]
        if all_variants and all(v in exclude_fully_used for v in all_variants):
            continue

        result.append(name)
    return sorted(result)


def get_variants(base_name: str) -> list[str]:
    """Gibt alle Vollnamen (inkl. Variante) für eine Basisstrecke zurück."""
    all_tracks = _load_all_tracks()
    return [t["full_name"] for t in all_tracks if t["name"] == base_name]
