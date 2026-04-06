import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, date
import os
from dotenv import load_dotenv
import sheets
import tracks

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
VOTING_CHANNEL_ID = int(os.getenv("VOTING_CHANNEL_ID"))
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
DRIVER_ROLE_NAME = os.getenv("DRIVER_ROLE_NAME", "driver")

# Testmodus
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
TEST_ANNOUNCE_CHANNEL_ID = int(os.getenv("TEST_ANNOUNCE_CHANNEL_ID", "0")) if os.getenv("TEST_ANNOUNCE_CHANNEL_ID") else None
ORGA_ROLE_NAME = os.getenv("ORGA_ROLE_NAME", "orga")

def get_announce_channel_id() -> int:
    """Gibt je nach Modus die richtige Announce-Channel-ID zurück."""
    if TEST_MODE and TEST_ANNOUNCE_CHANNEL_ID:
        return TEST_ANNOUNCE_CHANNEL_ID
    return ANNOUNCE_CHANNEL_ID

def get_active_role_name() -> str:
    """Gibt je nach Modus die Rolle zurück, die Zugriff auf den Voting-Channel hat."""
    return ORGA_ROLE_NAME if TEST_MODE else DRIVER_ROLE_NAME

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track whether announcements have already been sent today
announcement_state = {
    "started": False,
    "reminded": False,
    "ended": False,
    "last_check_date": None,
}


def get_welcome_embed(end_date: date) -> discord.Embed:
    embed = discord.Embed(
        title="🏎️ Streckenwahl",
        description=(
            "Willkommen zur Streckenwahl! Wählt eure drei Wunschstrecken für die nächste Saison.\n"
            "Ihr könnt eure Auswahl jederzeit ändern.\n\n"
            f"⏳ Die Abstimmung läuft bis zum **{end_date.strftime('%d.%m.%Y')}**.\n\n"
            "ℹ️ Das Saisonfinale wird traditionell auf der Nordschleife ausgetragen – "
            "Nürburgring 24h, Endurance und Nordschleife stehen daher nicht zur Auswahl."
        ),
        color=discord.Color.blue(),
    )
    return embed


async def set_channel_visibility(guild: discord.Guild, visible: bool):
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        return

    # Im Testmodus Orga-Rolle nicht anfassen (höherrangig als Bot)
    if TEST_MODE:
        print(f"[INFO] [TESTMODUS] Channel-Sichtbarkeit wird nicht geändert (Orga hat dauerhaft Zugriff).")
        return

    role_name = get_active_role_name()
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        print(f"[WARN] Rolle '{role_name}' nicht gefunden.")
        return

    if visible:
        await channel.set_permissions(role, view_channel=True, send_messages=False)
        print(f"[INFO] Voting-Channel ist jetzt sichtbar für Rolle '{role_name}'.")
    else:
        await channel.set_permissions(role, view_channel=False)
        print(f"[INFO] Voting-Channel ist jetzt unsichtbar für Rolle '{role_name}'.")


async def post_welcome_message(guild: discord.Guild, end_date: date):
    channel = guild.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        print(f"[ERROR] Channel {VOTING_CHANNEL_ID} nicht gefunden!")
        return
    perms = channel.permissions_for(guild.me)
    print(f"[DEBUG] Channel: {channel.name}, send_messages: {perms.send_messages}, view_channel: {perms.view_channel}")
    # Lösche alte Nachrichten des Bots im Channel
    if perms.read_message_history:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user:
                await msg.delete()
    embed = get_welcome_embed(end_date)
    view = WelcomeView()
    await channel.send(embed=embed, view=view)


@tasks.loop(hours=24)
async def daily_check():
    now = date.today()
    # Reset state bei neuem Tag
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
            await announce_channel.send(
                f"{mode_prefix}🏁 **Die Streckenwahl für die nächste Saison ist jetzt geöffnet!**\n"
                f"Gebt bis zum **{end_date.strftime('%d.%m.%Y')}** eure drei Wunschstrecken ab.\n"
                f"Zum Abstimmungs-Channel: <#{VOTING_CHANNEL_ID}>"
            )
        announcement_state["started"] = True

    # Erinnerung einen Tag vor dem Ende
    from datetime import timedelta
    if now == end_date - timedelta(days=1) and not announcement_state["reminded"]:
        if announce_channel:
            await announce_channel.send(
                f"{mode_prefix}⏰ **Erinnerung:** Die Streckenwahl endet morgen!\n"
                f"Noch nicht abgestimmt? Schnell, bis 23:59 Uhr: <#{VOTING_CHANNEL_ID}>"
            )
        announcement_state["reminded"] = True

    # Abstimmung endet heute (nach Mitternacht = Tag danach)
    if now > end_date and not announcement_state["ended"]:
        await set_channel_visibility(guild, False)
        if announce_channel:
            await announce_channel.send(
                f"{mode_prefix}🔒 **Die Streckenwahl ist abgeschlossen.**\n"
                "Danke an alle, die abgestimmt haben! Die Ergebnisse werden in den Rennkalender der nächsten Saison einfließen."
            )
        announcement_state["ended"] = True


@daily_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()
    # Warte bis Mitternacht für den ersten Lauf
    now = datetime.now()
    midnight = datetime(now.year, now.month, now.day, 0, 0, 5)
    from datetime import timedelta
    if now >= midnight:
        midnight += timedelta(days=1)
    wait_seconds = (midnight - now).total_seconds()
    print(f"[INFO] Erster Daily-Check in {wait_seconds:.0f} Sekunden (Mitternacht).")
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

    # Persistente Views registrieren
    bot.add_view(WelcomeView())

    daily_check.start()

    # Kurz warten bis Discord-Cache vollständig geladen ist
    await asyncio.sleep(5)
    # Sofort-Check beim Start (falls Bot neu gestartet wurde während Abstimmung läuft)
    await startup_check()


async def startup_check():
    """Prüft beim Bot-Start ob Abstimmung gerade aktiv sein sollte."""
    try:
        start_date, end_date = sheets.get_voting_dates()
    except Exception as e:
        print(f"[ERROR] Startup-Check fehlgeschlagen: {e}")
        return

    today = date.today()
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    if start_date <= today <= end_date:
        print("[INFO] Abstimmung ist aktiv – Channel wird sichtbar geschaltet.")
        await set_channel_visibility(guild, True)
        await asyncio.sleep(2)
        # Prüfe ob bereits eine Welcome-Nachricht existiert
        channel = guild.get_channel(VOTING_CHANNEL_ID)
        if channel:
            has_welcome = False
            perms = channel.permissions_for(guild.me)
            if perms.read_message_history:
                async for msg in channel.history(limit=10):
                    if msg.author == bot.user and msg.embeds:
                        has_welcome = True
                        break
            if not has_welcome:
                await post_welcome_message(guild, end_date)
    else:
        print("[INFO] Keine aktive Abstimmung – Channel bleibt unsichtbar.")
        await set_channel_visibility(guild, False)


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
        # Prüfe ob Abstimmung noch läuft
        try:
            start_date, end_date = sheets.get_voting_dates()
        except Exception:
            await interaction.response.send_message(
                "❌ Fehler beim Lesen der Abstimmungsdaten.", ephemeral=True
            )
            return

        today = date.today()
        if not (start_date <= today <= end_date):
            await interaction.response.send_message(
                "❌ Die Abstimmung ist aktuell nicht aktiv.", ephemeral=True
            )
            return

        # Starte Voting-Flow für Wunsch 1
        view = ContinentSelectView(wish_number=1, existing_wishes={})
        await interaction.response.send_message(
            embed=wish_embed(1), view=view, ephemeral=True
        )


def wish_embed(wish_number: int, selected: dict = None) -> discord.Embed:
    titles = {1: "Erster Wunsch", 2: "Zweiter Wunsch", 3: "Dritter Wunsch"}
    embed = discord.Embed(
        title=f"🏎️ Schritt {wish_number}/3 – {titles[wish_number]}",
        color=discord.Color.orange(),
    )
    if selected:
        embed.add_field(name="Bereits gewählt", value="\n".join(
            [f"{i}. {t}" for i, t in selected.items()]
        ), inline=False)
    embed.set_footer(text="Wähle zuerst den Kontinent, dann die Strecke.")
    return embed


def result_embed(wishes: dict) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Deine Streckenauswahl",
        description="Deine Wünsche wurden eingetragen. Du kannst sie jederzeit ändern.",
        color=discord.Color.green(),
    )
    for i, track in wishes.items():
        embed.add_field(name=f"Wunsch {i}", value=track, inline=False)
    return embed


class ContinentSelectView(discord.ui.View):
    def __init__(self, wish_number: int, existing_wishes: dict):
        super().__init__(timeout=300)
        self.wish_number = wish_number
        self.existing_wishes = existing_wishes
        self.add_item(ContinentSelect(wish_number, existing_wishes))


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
        continent = self.values[0]
        track_list = tracks.get_tracks_by_continent(continent)

        view = TrackSelectView(
            wish_number=self.wish_number,
            continent=continent,
            track_list=track_list,
            existing_wishes=self.existing_wishes,
        )
        await interaction.response.edit_message(
            embed=wish_embed(self.wish_number, self.existing_wishes), view=view
        )


class TrackSelectView(discord.ui.View):
    def __init__(self, wish_number, continent, track_list, existing_wishes):
        super().__init__(timeout=300)
        self.add_item(TrackSelect(wish_number, continent, track_list, existing_wishes))


class TrackSelect(discord.ui.Select):
    def __init__(self, wish_number, continent, track_list, existing_wishes):
        self.wish_number = wish_number
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
        selected_track = self.values[0]
        variants = tracks.get_variants(selected_track)

        if len(variants) <= 1:
            # Keine Variantenauswahl nötig
            full_name = variants[0] if variants else selected_track
            await finalize_wish(interaction, self.wish_number, full_name, self.existing_wishes)
        else:
            view = VariantSelectView(
                wish_number=self.wish_number,
                track_name=selected_track,
                variants=variants,
                existing_wishes=self.existing_wishes,
            )
            embed = wish_embed(self.wish_number, self.existing_wishes)
            embed.add_field(name="Strecke", value=selected_track, inline=False)
            embed.set_footer(text="Wähle jetzt die Variante.")
            await interaction.response.edit_message(embed=embed, view=view)


class VariantSelectView(discord.ui.View):
    def __init__(self, wish_number, track_name, variants, existing_wishes):
        super().__init__(timeout=300)
        self.add_item(VariantSelect(wish_number, track_name, variants, existing_wishes))


class VariantSelect(discord.ui.Select):
    def __init__(self, wish_number, track_name, variants, existing_wishes):
        self.wish_number = wish_number
        self.existing_wishes = existing_wishes
        options = [
            discord.SelectOption(label=v, value=v)
            for v in variants[:25]
        ]
        super().__init__(
            placeholder="Variante wählen...",
            options=options,
            custom_id=f"variant_select_{wish_number}",
        )

    async def callback(self, interaction: discord.Interaction):
        selected_variant = self.values[0]
        await finalize_wish(interaction, self.wish_number, selected_variant, self.existing_wishes)


async def finalize_wish(interaction: discord.Interaction, wish_number: int, full_track: str, existing_wishes: dict):
    # Doppelungs-Check
    if full_track in existing_wishes.values():
        await interaction.response.send_message(
            f"⚠️ **{full_track}** hast du bereits gewählt. Bitte wähle eine andere Strecke.",
            ephemeral=True,
        )
        return

    existing_wishes[wish_number] = full_track

    if wish_number < 3:
        # Nächster Wunsch
        view = ContinentSelectView(wish_number=wish_number + 1, existing_wishes=existing_wishes)
        await interaction.response.edit_message(
            embed=wish_embed(wish_number + 1, existing_wishes), view=view
        )
    else:
        # Alle 3 Wünsche gesetzt → ins Sheet schreiben
        try:
            sheets.write_votes(interaction.user, existing_wishes)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Fehler beim Speichern: {e}", embed=None, view=None
            )
            return

        # Ergebnis-Ansicht mit Ändern-Buttons
        view = ResultView(wishes=existing_wishes)
        await interaction.response.edit_message(
            embed=result_embed(existing_wishes), view=view
        )


class ResultView(discord.ui.View):
    def __init__(self, wishes: dict):
        super().__init__(timeout=None)
        self.wishes = wishes
        for i in range(1, 4):
            self.add_item(ChangeWishButton(wish_number=i, wishes=wishes))


class ChangeWishButton(discord.ui.Button):
    def __init__(self, wish_number: int, wishes: dict):
        self.wish_number = wish_number
        self.wishes = wishes
        super().__init__(
            label="Ändern",
            style=discord.ButtonStyle.secondary,
            emoji="✏️",
            custom_id=f"change_wish_{wish_number}_{id(wishes)}",
            row=wish_number - 1,
        )

    async def callback(self, interaction: discord.Interaction):
        # Starte nur den Dialog für diesen einen Wunsch
        modified_wishes = dict(self.wishes)
        view = ContinentSelectView(
            wish_number=self.wish_number,
            existing_wishes={k: v for k, v in modified_wishes.items() if k != self.wish_number},
        )
        await interaction.response.edit_message(
            embed=wish_embed(self.wish_number, {k: v for k, v in modified_wishes.items() if k != self.wish_number}),
            view=view,
        )


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
