"""
reset_voting.py
---------------
Dieses Script zwingt den Bot, beim nächsten Start die Begrüßungsnachricht
neu zu posten. Es löscht dazu eine Marker-Datei (falls vorhanden) und
gibt eine Anleitung aus.

Aufruf: python3 reset_voting.py
"""

import discord
import asyncio
import os
from dotenv import load_dotenv
import sheets

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
VOTING_CHANNEL_ID = int(os.getenv("VOTING_CHANNEL_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"[INFO] Eingeloggt als {client.user}")
    channel = client.get_channel(VOTING_CHANNEL_ID)
    if not channel:
        print(f"[ERROR] Channel {VOTING_CHANNEL_ID} nicht gefunden!")
        await client.close()
        return

    # Alle Bot-Nachrichten im Voting-Channel löschen
    deleted = 0
    async for msg in channel.history(limit=50):
        if msg.author == client.user:
            await msg.delete()
            deleted += 1

    print(f"[INFO] {deleted} Bot-Nachricht(en) im Voting-Channel gelöscht.")
    print(f"[INFO] Starte jetzt den Bot neu mit:")
    print(f"       sudo systemctl restart rtc-trackvotebot")
    print(f"       Der Bot wird dann die Begrüßungsnachricht neu posten.")
    await client.close()


client.run(DISCORD_TOKEN)
