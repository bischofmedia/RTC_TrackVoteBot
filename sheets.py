import os
from datetime import date, datetime
import gspread
from google.oauth2.service_account import Credentials
import discord

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Farbe Rot für nicht gefundene Fahrer
RED_BG = {"backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}}
RED_TEXT = {
    "textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}},
}


def get_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.Client(auth=creds)
    client.set_timeout(30)
    return client


def get_voting_dates() -> tuple[date, date]:
    """Liest Start- und Enddatum aus TrackVoting L15 und L16."""
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("TrackVoting")
    start_val = ws.acell("L15").value
    end_val = ws.acell("L16").value
    start_date = datetime.strptime(start_val.strip(), "%d.%m.%Y").date()
    end_date = datetime.strptime(end_val.strip(), "%d.%m.%Y").date()
    return start_date, end_date


def get_psn_name(discord_name: str) -> str | None:
    """Sucht PSN-Namen anhand des Discord-Namens in DB_drvr."""
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("DB_drvr")
    # Spalte J = 10, Spalte C = 3, ab Zeile 5
    all_values = ws.get_all_values()
    for row in all_values[4:]:  # ab Zeile 5 (Index 4)
        if len(row) >= 10:
            discord_col = row[9].strip()   # Spalte J
            psn_col = row[2].strip()       # Spalte C
            if discord_col.lower() == discord_name.lower() and psn_col:
                return psn_col
    return None


def get_tracks_from_sheet() -> list[dict]:
    """Liest Streckenliste aus DB_tech (Spalte M = Name, N = Ländercode)."""
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("DB_tech")
    all_values = ws.get_all_values()
    excluded = [t.strip() for t in os.getenv("EXCLUDED_TRACKS", "").split(",") if t.strip()]
    result = []
    for row in all_values[7:]:  # ab Zeile 8 (Index 7)
        if len(row) < 14:
            continue
        name = row[12].strip()   # Spalte M
        code = row[13].strip()   # Spalte N
        if not name or name.upper() == "PAUSE":
            break
        if name in excluded:
            continue
        if code:
            result.append({"name": name, "code": code.strip().upper()})
        else:
            result.append({"name": name, "code": None})
    return result


def find_existing_vote_row(ws, name: str) -> int | None:
    """Sucht ob bereits eine Zeile für diesen Namen existiert."""
    col_b = ws.col_values(2)  # Spalte B
    for i, val in enumerate(col_b[1:], start=2):  # ab Zeile 2
        if val.strip().lower() == name.lower():
            return i
    return None


def write_votes(user: discord.User, wishes: dict, nickname: str | None = None):
    """Schreibt oder überschreibt die Votes eines Fahrers."""
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("TrackVoting")

    discord_name = str(user.name)
    psn_name = get_psn_name(discord_name)
    name_found = psn_name is not None
    if name_found:
        display_name = psn_name
    elif nickname:
        display_name = nickname
    else:
        display_name = discord_name

    existing_row = find_existing_vote_row(ws, display_name)

    if existing_row:
        row_num = existing_row
        # Bestehende Wünsche aus dem Sheet lesen um nur gesetzte zu überschreiben
        existing = ws.row_values(row_num)
        def current(col_idx):
            return existing[col_idx].strip() if len(existing) > col_idx else ""
        track1 = wishes.get(1, "") or current(3)  # Spalte D = Index 3
        track2 = wishes.get(2, "") or current(4)  # Spalte E = Index 4
        track3 = wishes.get(3, "") or current(5)  # Spalte F = Index 5
    else:
        # Neue Zeile
        col_b = ws.col_values(2)
        row_num = len(col_b) + 1
        if row_num < 2:
            row_num = 2
        track1 = wishes.get(1, "")
        track2 = wishes.get(2, "")
        track3 = wishes.get(3, "")

    # Werte schreiben: B, D, E, F
    ws.update_cell(row_num, 2, display_name)   # Spalte B
    ws.update_cell(row_num, 4, track1)          # Spalte D
    ws.update_cell(row_num, 5, track2)          # Spalte E
    ws.update_cell(row_num, 6, track3)          # Spalte F

    # Rot markieren wenn nicht gefunden
    if not name_found:
        sheet_id = ws._properties["sheetId"]
        body = {
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_num - 1,
                            "endRowIndex": row_num,
                            "startColumnIndex": 1,  # Spalte B
                            "endColumnIndex": 2,
                        },
                        "cell": {
                            "userEnteredFormat": RED_TEXT
                        },
                        "fields": "userEnteredFormat.textFormat.foregroundColor",
                    }
                }
            ]
        }
        sh.batch_update(body)


def read_votes(user: discord.User) -> dict:
    """Liest die aktuellen Votes eines Fahrers aus dem Sheet.
    Gibt {1: "Track1", 2: "Track2", 3: "Track3"} zurück, fehlende als "".
    """
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("TrackVoting")

    discord_name = str(user.name)
    psn_name = get_psn_name(discord_name)
    display_name = psn_name if psn_name else discord_name

    row_num = find_existing_vote_row(ws, display_name)
    if not row_num:
        return {}

    row = ws.row_values(row_num)
    # Spalte D=4, E=5, F=6 (Index 3,4,5)
    def cell(idx):
        return row[idx].strip() if len(row) > idx else ""

    result = {}
    for i, idx in enumerate([3, 4, 5], start=1):
        val = cell(idx)
        if val:
            result[i] = val
    return result


def clear_wish(user: discord.User, wish_number: int):
    """Löscht einen einzelnen Wunsch-Slot im Sheet (setzt ihn auf leer)."""
    gc = get_client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = sh.worksheet("TrackVoting")

    discord_name = str(user.name)
    psn_name = get_psn_name(discord_name)
    display_name = psn_name if psn_name else discord_name

    row_num = find_existing_vote_row(ws, display_name)
    if not row_num:
        return  # Noch kein Eintrag, nichts zu löschen

    col_map = {1: 4, 2: 5, 3: 6}  # Wunsch → Spalte (D, E, F)
    col = col_map.get(wish_number)
    if col:
        ws.update_cell(row_num, col, "")
