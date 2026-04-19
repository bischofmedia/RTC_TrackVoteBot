import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, date, timedelta
import os
import pytz
from dotenv import load_dotenv

load_dotenv()

import sheets
import tracks

DISCORD_TOKEN          = os.getenv("DISCORD_TOKEN")
VOTING_CHANNEL_ID      = int(os.getenv("VOTING_CHANNEL_ID"))
ANNOUNCE_CHANNEL_ID    = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
ORGA_CHANNEL_ID        = int(os.getenv("ORGA_CHANNEL_ID"))
DRIVER_ROLE_NAME       = os.getenv("DRIVER_ROLE_NAME", "driver")
ORGA_ROLE_NAME         = os.getenv("ORGA_ROLE_NAME", "orga")
TIMEZONE               = os.getenv("TIMEZONE", "Europe/Berlin")

TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
IGAL_MODE = os.getenv("EGAL", "false").lower() == "true"
TEST_ANNOUNCE_CHANNEL_ID = int(os.getenv("TEST_ANNOUNCE_CHANNEL_ID", "0")) if os.getenv("TEST_ANNOUNCE_CHANNEL_ID") else None

TXT_WELCOME_TITLE       = os.getenv("TXT_WELCOME_TITLE", "🏎️ Streckenwahl")
TXT_WELCOME_BODY        = os.getenv("TXT_WELCOME_BODY",
    "Willkommen zur Streckenwahl! Wählt eure drei Wunschstrecken für die nächste Saison.\n"
    "Ihr könnt eure Auswahl jederzeit ändern.\n\n"
    "⏳ Die Abstimmung läuft bis zum **{end_date}**.\n\n"
    "ℹ️ Das Saisonfinale wird traditionell auf der Nordschleife ausgetragen – "
    "Nürburgring 24h, Endurance und Nordschleife stehen daher nicht zur Auswahl.")
TXT_NO_VOTING           = os.getenv("TXT_NO_VOTING",
    "🏁 Aktuell ist kein TrackVoting aktiv.")
TXT_VOTE_GREETING       = os.getenv("TXT_VOTE_GREETING",
    "👋 Hallo **{nickname}**, ich lade die Strecken – deine Streckenwahl startet in Kürze!\n\n"
    "Bitte wähle aus technischen Gründen erst den **Kontinent**, dann die **Strecke**, "
    "und falls vorhanden eine **Streckenvariante**.\n"
    "Du kannst deine Auswahl jederzeit wieder ändern, solange die Abstimmung läuft.")
TXT_ANNOUNCE_START      = os.getenv("TXT_ANNOUNCE_START",
    "{prefix}🏁 **Die Streckenwahl für die nächste Saison ist jetzt geöffnet!**\n"
    "Gebt bis zum **{end_date}** eure drei Wunschstrecken ab.\n"
    "Zum Abstimmungs-Channel: <#{channel_id}>")
TXT_ANNOUNCE_REMINDER   = os.getenv("TXT_ANNOUNCE_REMINDER",
    "{prefix}⏰ **Erinnerung:** Die Streckenwahl endet heute um 23:59 Uhr!\n"
    "Noch nicht abgestimmt? Schnell: <#{channel_id}>")
TXT_ANNOUNCE_END        = os.getenv("TXT_ANNOUNCE_END",
    "{prefix}🔒 **Die Streckenwahl ist abgeschlossen.**\n"
    "Danke an alle, die abgestimmt haben! Die Ergebnisse werden in den Rennkalender der nächsten Saison einfließen.")
TXT_ORGA_CHANNEL_OPEN   = os.getenv("TXT_ORGA_CHANNEL_OPEN",
    "✅ Abstimmungs-Channel wurde für die Rolle **{role}** **geöffnet** (sichtbar, kein Schreiben).")
TXT_ORGA_CHANNEL_CLOSE  = os.getenv("TXT_ORGA_CHANNEL_CLOSE",
    "🔒 Abstimmungs-Channel wurde für die Rolle **{role}** **geschlossen** (nicht sichtbar).")
TXT_TIMEOUT_MSG         = os.getenv("TXT_TIMEOUT_MSG",
    "⏸️ **Kein Problem – nimm dir Zeit!**\n"
    "Deine bisherige Auswahl wurde gespeichert. "
    "Klicke auf den Button, um dort weiterzumachen, wo du aufgehört hast.")
TXT_RESULT_HINT         = os.getenv("TXT_RESULT_HINT",
    "⬇️ *Klicke auf einen der Buttons unten, um eine Strecke zu ändern.*")
TXT_RESULT_DESC         = os.getenv("TXT_RESULT_DESC",
    "Deine Wünsche wurden eingetragen. Du kannst sie jederzeit ändern, solange die Abstimmung läuft.")
TXT_WISH_FOOTER         = os.getenv("TXT_WISH_FOOTER",
    "Wähle zuerst den Kontinent, dann die Strecke.")


def get_announce_channel_id() -> int:
    if TEST_MODE and TEST_ANNOUNCE_CHANNEL_ID:
        return TEST_ANNOUNCE_CHANNEL_ID
    return ANNOUNCE_CHANNEL_ID

def get_active_role_name() -> str:
    return ORGA_ROLE_NAME if TEST_MODE else DRIVER_ROLE_NAME

def local_now() -> datetime:
    return datetime.now(pytz.timezone(TIMEZONE))

def local_today() -> date:
    return local_now().date()

def local_midnight_utc() -> datetime:
    """Nächste Berliner Mitternacht als UTC."""
    tz = pytz.timezone(TIMEZONE)
    now_local = local_now()
    midnight_local = now_local.replace(hour=0, minute=0, second=5, microsecond=0)
    if now_local >= midnight_local:
        midnight_local += timedelta(days=1)
    return midnight_local.astimezone(pytz.utc)

def local_2359_utc() -> datetime:
    """Heutiges 23:59:00 Berliner Zeit als UTC."""
    tz = pytz.timezone(TIMEZONE)
    now_local = local_now()
    target = now_local.replace(hour=23, minute=59, second=0, microsecond=0)
    if now_local >= target:
        target += timedelta(days=1)
    return target.astimezone(pytz.utc)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

announcement_state = {
    "started": False,
    "reminded": False,
    "ended": False,
    "last_check_date": None,
}


def get_welcome_embed(end_date: date) -> discord.Embed:
    embed = discord.Embed(
        title=TXT_WELCOME_TITLE,
        description=TXT_WELCOME_BODY.format(end_date=end_date.strftime("%d.%m.%Y")),
        color=discord.Color.blue(),
    )
    return embed


async def clear_voting_channel(guild: discord.Guild):
    """Löscht alle Bot-Nachrichten im Voting-Channel."""
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return
    perms = channel.permissions_for(guild.me)
    if not perms.read_message_history:
        return
    deleted = 0
    async for msg in channel.history(limit=100):
        if msg.author == bot.user:
            await msg.delete()
            deleted += 1
    print(f"[INFO] Voting-Channel geleert ({deleted} Nachrichten gelöscht).")


async def post_no_voting_message(guild: discord.Guild):
    """Postet die 'Kein Voting aktiv'-Nachricht in den Voting-Channel."""
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return
    await clear_voting_channel(guild)
    await channel.send(TXT_NO_VOTING)


async def post_welcome_message(guild: discord.Guild, end_date: date):
    """Postet das Welcome-Embed mit Abstimmen-Button."""
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        print(f"[ERROR] Channel {VOTING_CHANNEL_ID} nicht gefunden!")
        return
    perms = channel.permissions_for(guild.me)
    print(f"[DEBUG] Channel: {channel.name}, send_messages: {perms.send_messages}, view_channel: {perms.view_channel}")
    await clear_voting_channel(guild)
    embed = get_welcome_embed(end_date)
    view = WelcomeView()
    await channel.send(embed=embed, view=view)


async def set_channel_visibility(guild: discord.Guild, visible: bool, notify: bool = True):
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return

    orga_channel = guild.get_channel(ORGA_CHANNEL_ID) if notify else None
    role_name = get_active_role_name()

    if TEST_MODE:
        print(f"[INFO] [TESTMODUS] Channel-Sichtbarkeit wird nicht geändert.")
        return

    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        print(f"[WARN] Rolle '{role_name}' nicht gefunden.")
        return

    if visible:
        await channel.set_permissions(role,
            view_channel=True,
            send_messages=False,
            read_messages=True,
            read_message_history=True,
            use_application_commands=True,
        )
        print(f"[INFO] Voting-Channel geöffnet für '{role_name}'.")
        if orga_channel:
            await orga_channel.send(TXT_ORGA_CHANNEL_OPEN.format(role=role_name))
    else:
        await channel.set_permissions(role, view_channel=False)
        print(f"[INFO] Voting-Channel geschlossen für '{role_name}'.")
        if orga_channel:
            await orga_channel.send(TXT_ORGA_CHANNEL_CLOSE.format(role=role_name))


async def channel_has_welcome(guild: discord.Guild) -> bool:
    """Prüft ob bereits ein Welcome-Embed im Channel ist."""
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return False
    perms = channel.permissions_for(guild.me)
    if not perms.read_message_history:
        return False
    async for msg in channel.history(limit=10):
        if msg.author == bot.user and msg.embeds:
            return True
    return False


async def channel_has_no_voting_msg(guild: discord.Guild) -> bool:
    """Prüft ob bereits eine 'Kein Voting'-Nachricht im Channel ist."""
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return False
    perms = channel.permissions_for(guild.me)
    if not perms.read_message_history:
        return False
    async for msg in channel.history(limit=10):
        if msg.author == bot.user and not msg.embeds and TXT_NO_VOTING in msg.content:
            return True
    return False


# ──────────────────────────────────────────────
# DAILY CHECK – läuft täglich um Berliner Mitternacht
# Zuständig für: Start, Erinnerung (am End-Tag)
# ──────────────────────────────────────────────

@tasks.loop(hours=24)
async def daily_check():
    now = local_today()
    if announcement_state["last_check_date"] != now:
        announcement_state["last_check_date"] = now
        announcement_state["started"] = False
        announcement_state["reminded"] = False
        announcement_state["ended"] = False

    try:
        start_date, end_date = sheets.get_voting_dates()
    except Exception as e:
        print(f"[ERROR] Konnte Abstimmungsdaten nicht lesen: {e}")
        return

    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    announce_channel = guild.get_channel(get_announce_channel_id())
    mode_prefix = "🧪 **[TESTMODUS]** " if TEST_MODE else ""

    # Abstimmung startet heute
    if now == start_date and not announcement_state["started"]:
        await set_channel_visibility(guild, True)
        await post_welcome_message(guild, end_date)
        if announce_channel:
            await announce_channel.send(TXT_ANNOUNCE_START.format(
                prefix=mode_prefix,
                end_date=end_date.strftime("%d.%m.%Y"),
                channel_id=VOTING_CHANNEL_ID,
            ))
        announcement_state["started"] = True

    # Erinnerung am End-Tag um Mitternacht (nur wenn nicht gleichzeitig Start)
    if now == end_date and now != start_date and not announcement_state["reminded"]:
        if announce_channel:
            await announce_channel.send(TXT_ANNOUNCE_REMINDER.format(
                prefix=mode_prefix,
                channel_id=VOTING_CHANNEL_ID,
            ))
        announcement_state["reminded"] = True


@daily_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()
    midnight_utc = local_midnight_utc()
    now_utc = datetime.now(pytz.utc)
    wait_seconds = (midnight_utc - now_utc).total_seconds()
    print(f"[INFO] Erster Daily-Check in {wait_seconds:.0f} Sekunden (Mitternacht {TIMEZONE}).")
    await asyncio.sleep(wait_seconds)


# ──────────────────────────────────────────────
# END CHECK – läuft täglich um 23:59 Berliner Zeit
# Zuständig für: Abstimmungsende
# ──────────────────────────────────────────────

@tasks.loop(hours=24)
async def end_check():
    now = local_today()

    try:
        start_date, end_date = sheets.get_voting_dates()
    except Exception as e:
        print(f"[ERROR] End-Check: Konnte Abstimmungsdaten nicht lesen: {e}")
        return

    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    announce_channel = guild.get_channel(get_announce_channel_id())
    mode_prefix = "🧪 **[TESTMODUS]** " if TEST_MODE else ""

    # Abstimmung endet heute um 23:59
    if now == end_date and not announcement_state["ended"]:
        await set_channel_visibility(guild, False)
        await post_no_voting_message(guild)
        if announce_channel:
            await announce_channel.send(TXT_ANNOUNCE_END.format(prefix=mode_prefix))
        announcement_state["ended"] = True
        print(f"[INFO] Abstimmung beendet ({end_date}).")


@end_check.before_loop
async def before_end_check():
    await bot.wait_until_ready()
    target_utc = local_2359_utc()
    now_utc = datetime.now(pytz.utc)
    wait_seconds = (target_utc - now_utc).total_seconds()
    print(f"[INFO] End-Check läuft in {wait_seconds:.0f} Sekunden (23:59 {TIMEZONE}).")
    await asyncio.sleep(wait_seconds)


@bot.event
async def on_ready():
    print(f"[INFO] {bot.user} ist online.")
    if TEST_MODE:
        print(f"[INFO] ⚠️  TESTMODUS AKTIV – Zugriff nur für Rolle '{ORGA_ROLE_NAME}', Nachrichten in Test-Channel.")
    try:
        synced = await bot.tree.sync()
        print(f"[INFO] {len(synced)} Slash-Commands synchronisiert.")
    except Exception as e:
        print(f"[ERROR] Slash-Command Sync fehlgeschlagen: {e}")

    bot.add_view(WelcomeView())
    daily_check.start()
    end_check.start()

    await asyncio.sleep(5)
    await startup_check()


async def startup_check():
    """Prüft beim Bot-Start ob Abstimmung gerade aktiv sein sollte,
    und stellt sicher dass immer eine passende Nachricht im Channel steht."""
    try:
        start_date, end_date = sheets.get_voting_dates()
    except Exception as e:
        print(f"[ERROR] Startup-Check fehlgeschlagen: {e}")
        return

    today = local_today()
    now = local_now()
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    if start_date <= today <= end_date:
        # Abstimmung läuft – aber ist sie bereits um 23:59 vorbei?
        end_of_day = now.replace(hour=23, minute=59, second=0, microsecond=0)
        if today == end_date and now >= end_of_day:
            # End-Tag nach 23:59 – Abstimmung bereits beendet
            print("[INFO] Abstimmung bereits beendet (nach 23:59 am End-Tag).")
            await set_channel_visibility(guild, False, notify=False)
            if not await channel_has_no_voting_msg(guild):
                await post_no_voting_message(guild)
        else:
            print("[INFO] Abstimmung ist aktiv – Channel wird sichtbar geschaltet.")
            await set_channel_visibility(guild, True, notify=False)
            await asyncio.sleep(2)
            if not await channel_has_welcome(guild):
                await post_welcome_message(guild, end_date)
    else:
        print("[INFO] Keine aktive Abstimmung – Channel bleibt unsichtbar.")
        await set_channel_visibility(guild, False, notify=False)
        if not await channel_has_no_voting_msg(guild):
            await post_no_voting_message(guild)


# ──────────────────────────────────────────────
# VIEWS & MODALS
# ──────────────────────────────────────────────

class WelcomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abstimmen",
        style=discord.ButtonStyle.primary,
        emoji="🏁",
        custom_id="welcome_vote_button",
    )
    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else interaction.user.name
        await interaction.followup.send(
            TXT_VOTE_GREETING.format(nickname=nickname),
            ephemeral=True,
        )

        try:
            start_date, end_date = sheets.get_voting_dates()
        except Exception:
            await interaction.followup.send("❌ Fehler beim Lesen der Abstimmungsdaten.", ephemeral=True)
            return

        today = local_today()
        if not (start_date <= today <= end_date):
            await interaction.followup.send("❌ Die Abstimmung ist aktuell nicht aktiv.", ephemeral=True)
            return

        # Prüfen ob bereits Votes vorhanden – dann direkt Result-Ansicht zeigen
        try:
            existing_wishes = await asyncio.get_event_loop().run_in_executor(
                None, sheets.read_votes, interaction.user
            )
        except Exception:
            existing_wishes = {}

        if len(existing_wishes) == 3:
            # Alle drei Wünsche bereits abgegeben → direkt zur Ergebnisansicht
            view = ResultView(wishes=existing_wishes)
            await interaction.followup.send(
                content=TXT_RESULT_HINT,
                embed=result_embed(existing_wishes),
                view=view,
                ephemeral=True,
            )
        elif existing_wishes:
            # Teilweise abgestimmt → beim nächsten fehlenden Wunsch weitermachen
            next_wish = next(i for i in range(1, 4) if i not in existing_wishes)
            view = ContinentSelectView(wish_number=next_wish, existing_wishes=existing_wishes, user=interaction.user)
            msg = await interaction.followup.send(embed=wish_embed(next_wish, existing_wishes), view=view, ephemeral=True)
            view._msg = msg
        else:
            # Noch keine Votes → von vorne beginnen
            view = ContinentSelectView(wish_number=1, existing_wishes={}, user=interaction.user)
            msg = await interaction.followup.send(embed=wish_embed(1), view=view, ephemeral=True)
            view._msg = msg


def wish_embed(wish_number: int, selected: dict = None, show_footer: bool = True) -> discord.Embed:
    titles = {1: "Erster Wunsch", 2: "Zweiter Wunsch", 3: "Dritter Wunsch"}
    embed = discord.Embed(
        title=f"🏎️ Schritt {wish_number}/3 – {titles[wish_number]}",
        color=discord.Color.orange(),
    )
    if selected:
        embed.add_field(name="Bereits gewählt", value="\n".join(
            [f"{i}. {t}" for i, t in selected.items()]
        ), inline=False)
    if show_footer:
        embed.set_footer(text=TXT_WISH_FOOTER)
    return embed


def result_embed(wishes: dict) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Deine Streckenauswahl",
        description=TXT_RESULT_DESC,
        color=discord.Color.green(),
    )
    for i, track in wishes.items():
        embed.add_field(name=f"Wunsch {i}", value=track, inline=False)
    return embed


class ContinentSelectView(discord.ui.View):
    def __init__(self, wish_number: int, existing_wishes: dict, user=None):
        super().__init__(timeout=300)
        self.wish_number = wish_number
        self.existing_wishes = existing_wishes
        self.user = user
        self._msg = None  # wird nach followup.send() gesetzt
        self.add_item(ContinentSelect(wish_number, existing_wishes))

    async def on_timeout(self):
        view = ResumeView(user=self.user)
        msg = self._msg or self.message
        if msg:
            try:
                await msg.edit(content=TXT_TIMEOUT_MSG, embed=None, view=view)
            except Exception:
                pass


class ContinentSelect(discord.ui.Select):
    def __init__(self, wish_number: int, existing_wishes: dict):
        self.wish_number = wish_number
        self.existing_wishes = existing_wishes
        options = [
            discord.SelectOption(label="🌍 Europa", value="europa"),
            discord.SelectOption(label="🌎 Amerika", value="amerika"),
            discord.SelectOption(label="🌏 Asien & Ozeanien", value="asien"),
        ]
        super().__init__(
            placeholder="Kontinent wählen...",
            options=options,
            custom_id=f"continent_select_{wish_number}",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        continent = self.values[0]
        continent_labels = {
            "europa": "🌍 Europa",
            "amerika": "🌎 Amerika",
            "asien": "🌏 Asien & Ozeanien",
        }
        continent_label = continent_labels.get(continent, continent.capitalize())

        # Fehlende Wünsche aus Sheet nachladen (z.B. nach Bot-Neustart)
        try:
            fresh = await asyncio.get_event_loop().run_in_executor(
                None, sheets.read_votes, interaction.user
            )
            for k, v in fresh.items():
                if k not in self.existing_wishes and k != self.wish_number:
                    self.existing_wishes[k] = v
        except Exception:
            pass

        already_chosen = set(self.existing_wishes.values())
        track_list = tracks.get_tracks_by_continent(continent, exclude_fully_used=already_chosen)

        view = TrackSelectView(
            wish_number=self.wish_number,
            continent=continent,
            continent_label=continent_label,
            track_list=track_list,
            existing_wishes=self.existing_wishes,
        )
        embed = wish_embed(self.wish_number, self.existing_wishes, show_footer=False)
        embed.add_field(
            name=f"Kontinent: {continent_label}",
            value=f"Folgende Strecken aus **{continent_label}** können gewählt werden:",
            inline=False,
        )
        await interaction.edit_original_response(embed=embed, view=view)


class TrackSelectView(discord.ui.View):
    def __init__(self, wish_number, continent, track_list, existing_wishes, continent_label="", user=None):
        super().__init__(timeout=300)
        self.user = user
        self.existing_wishes = existing_wishes
        self._msg = None
        self.add_item(TrackSelect(wish_number, continent, continent_label, track_list, existing_wishes))

    async def on_timeout(self):
        view = ResumeView(user=self.user)
        msg = self._msg or self.message
        if msg:
            try:
                await msg.edit(content=TXT_TIMEOUT_MSG, embed=None, view=view)
            except Exception:
                pass


class TrackSelect(discord.ui.Select):
    def __init__(self, wish_number, continent, continent_label, track_list, existing_wishes):
        self.wish_number = wish_number
        self.continent_label = continent_label
        self.existing_wishes = existing_wishes
        options = [
            discord.SelectOption(label=t, value=t)
            for t in track_list[:25]
        ]
        super().__init__(
            placeholder="Strecke wählen...",
            options=options,
            custom_id=f"track_select_{wish_number}",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_track = self.values[0]
        already_chosen = set(self.existing_wishes.values())
        all_variants = tracks.get_variants(selected_track)
        available_variants = [v for v in all_variants if v not in already_chosen]

        if not available_variants:
            await interaction.followup.send(
                f"⚠️ Für **{selected_track}** sind alle Varianten bereits gewählt. Bitte wähle eine andere Strecke.",
                ephemeral=True,
            )
            return
        if len(available_variants) == 1:
            await finalize_wish(interaction, self.wish_number, available_variants[0], self.existing_wishes)
        else:
            view = VariantSelectView(
                wish_number=self.wish_number,
                track_name=selected_track,
                variants=available_variants,
                existing_wishes=self.existing_wishes,
            )
            embed = wish_embed(self.wish_number, self.existing_wishes, show_footer=False)
            embed.add_field(
                name=f"Strecke: ***{selected_track}***",
                value=f"Für den Track ***{selected_track}*** stehen mehrere Varianten zur Wahl:",
                inline=False,
            )
            await interaction.edit_original_response(embed=embed, view=view)


class VariantSelectView(discord.ui.View):
    def __init__(self, wish_number, track_name, variants, existing_wishes, user=None):
        super().__init__(timeout=300)
        self.user = user
        self.existing_wishes = existing_wishes
        self._msg = None
        self.add_item(VariantSelect(wish_number, track_name, variants, existing_wishes))

    async def on_timeout(self):
        view = ResumeView(user=self.user)
        msg = self._msg or self.message
        if msg:
            try:
                await msg.edit(content=TXT_TIMEOUT_MSG, embed=None, view=view)
            except Exception:
                pass


ALLE_VARIANTEN_LABEL = "🎯 Sämtliche Varianten"

class VariantSelect(discord.ui.Select):
    def __init__(self, wish_number, track_name, variants, existing_wishes):
        self.wish_number = wish_number
        self.track_name = track_name
        self.existing_wishes = existing_wishes

        options = []
        # EGAL-Modus: "Sämtliche Varianten" nur anbieten wenn noch keine
        # Variante dieser Strecke bereits gewählt wurde
        already_chosen = set(existing_wishes.values())
        track_already_partially_chosen = any(
            v in already_chosen for v in variants
        )
        if IGAL_MODE and not track_already_partially_chosen:
            options.append(discord.SelectOption(
                label=ALLE_VARIANTEN_LABEL,
                value=ALLE_VARIANTEN_LABEL,
                description="Jede Variante ist okay",
            ))
        options += [
            discord.SelectOption(label=v, value=v)
            for v in variants[:24]  # max 24 + ggf. "Alle" = 25
        ]
        super().__init__(
            placeholder="Variante wählen...",
            options=options,
            custom_id=f"variant_select_{wish_number}",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_variant = self.values[0]
        await finalize_wish(interaction, self.wish_number, selected_variant, self.existing_wishes, track_name=self.track_name)


async def finalize_wish(interaction: discord.Interaction, wish_number: int, full_track: str, existing_wishes: dict, track_name: str = None):
    # EGAL-Modus: "Sämtliche Varianten" zu "<Strecke> - Alle Varianten" umwandeln
    if full_track == ALLE_VARIANTEN_LABEL and track_name:
        full_track = f"{track_name} - Alle Varianten"

    if full_track in existing_wishes.values():
        await interaction.followup.send(
            f"⚠️ **{full_track}** hast du bereits gewählt. Bitte wähle eine andere Strecke.",
            ephemeral=True,
        )
        return
    
    # Prüfen ob Strecken-Basisname bereits via "Alle Varianten" gewählt wurde
    if track_name:
        alle_key = f"{track_name} - Alle Varianten"
        if alle_key in existing_wishes.values():
            await interaction.followup.send(
                f"⚠️ Du hast bereits **alle Varianten von {track_name}** gewählt.",
                ephemeral=True,
            )
            return

    existing_wishes[wish_number] = full_track

    # Wenn alle 3 Wünsche gesetzt sind (auch bei Änderung) → direkt zur Ergebnisansicht
    all_set = all(i in existing_wishes and existing_wishes[i] for i in range(1, 4))

    if all_set:
        view = ResultView(wishes=existing_wishes)
        await interaction.edit_original_response(
            content=TXT_RESULT_HINT,
            embed=result_embed(existing_wishes),
            view=view,
        )
    elif wish_number < 3:
        view = ContinentSelectView(
            wish_number=wish_number + 1,
            existing_wishes=existing_wishes,
            user=interaction.user,
        )
        await interaction.edit_original_response(
            content=None,
            embed=wish_embed(wish_number + 1, existing_wishes),
            view=view,
        )
    else:
        view = ResultView(wishes=existing_wishes)
        await interaction.edit_original_response(
            content=TXT_RESULT_HINT,
            embed=result_embed(existing_wishes),
            view=view,
        )

    try:
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        nickname = member.display_name if member else None
        await asyncio.get_event_loop().run_in_executor(
            None, sheets.write_votes, interaction.user, existing_wishes, nickname
        )
    except Exception as e:
        print(f"[ERROR] Zwischenspeichern fehlgeschlagen: {e}")


class ResumeView(discord.ui.View):
    def __init__(self, user=None):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(
        label="Abstimmung fortsetzen",
        style=discord.ButtonStyle.primary,
        emoji="▶️",
        custom_id="resume_vote_button",
    )
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            current_wishes = await asyncio.get_event_loop().run_in_executor(
                None, sheets.read_votes, interaction.user
            )
        except Exception:
            current_wishes = {}

        next_wish = None
        for i in range(1, 4):
            if i not in current_wishes or not current_wishes[i]:
                next_wish = i
                break

        if next_wish is None:
            view = ResultView(wishes=current_wishes)
            await interaction.edit_original_response(
                content=TXT_RESULT_HINT,
                embed=result_embed(current_wishes),
                view=view,
            )
        else:
            view = ContinentSelectView(
                wish_number=next_wish,
                existing_wishes=current_wishes,
                user=interaction.user,
            )
            await interaction.edit_original_response(
                content=None,
                embed=wish_embed(next_wish, current_wishes),
                view=view,
            )


class ResultView(discord.ui.View):
    def __init__(self, wishes: dict):
        super().__init__(timeout=None)
        for i in range(1, 4):
            self.add_item(ChangeWishButton(wish_number=i, wishes=wishes))


class ChangeWishButton(discord.ui.Button):
    def __init__(self, wish_number: int, wishes: dict):
        self.wish_number = wish_number
        self.wishes = wishes
        track = wishes.get(wish_number, f"Wunsch {wish_number}")
        label = f"✏️ {track}"[:80]
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            custom_id=f"change_wish_{wish_number}",
            row=wish_number - 1,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Aktuellen Stand aus Sheet laden
        try:
            current_wishes = await asyncio.get_event_loop().run_in_executor(
                None, sheets.read_votes, interaction.user
            )
        except Exception:
            current_wishes = dict(self.wishes)

        # Zu ändernden Slot im Sheet leeren damit finalize_wish
        # beim Speichern den richtigen neuen Wert setzt
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, sheets.clear_wish, interaction.user, self.wish_number
            )
        except Exception as e:
            print(f"[WARN] clear_wish fehlgeschlagen: {e}")

        # Diesen Slot aus existing entfernen, Rest behalten
        existing = {k: v for k, v in current_wishes.items() if k != self.wish_number}
        view = ContinentSelectView(
            wish_number=self.wish_number,
            existing_wishes=existing,
            user=interaction.user,
        )
        await interaction.edit_original_response(
            content=None,
            embed=wish_embed(self.wish_number, existing),
            view=view,
        )


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
