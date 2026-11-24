import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN", "")
CLIENT_ID = os.getenv("CLIENT_ID", "0")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://discord.gg/")
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()}
LAVALINK = {
    "host": os.getenv("LAVALINK_HOST", ""),
    "port": int(os.getenv("LAVALINK_PORT", "443") or 443),
    "password": os.getenv("LAVALINK_PASSWORD", ""),
    "ssl": os.getenv("LAVALINK_SSL", "true").lower() == "true",
    "name": os.getenv("LAVALINK_NAME", "main"),
}
NP_LOG_CHANNEL = int(os.getenv("NOPREFIX_LOG_CHANNEL_ID") or 0)
INVITE_URL = (
    f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}"
    "&permissions=8&scope=bot%20applications.commands"
)

BOT_NAME = "Locus"
TEAM = "Nixo Devs"
DEVELOPER = "Shiv / Ghost 🌷"
PREFIX = os.getenv("BOT_PREFIX", "&")

# Container side-bar colors
HELP_COLOR = 0xFF0000
INFO_COLOR = 0x2B2D31
GREEN = 0x2ECC71
RED = 0xE74C3C
YELLOW = 0xF1C40F
BLURPLE = 0x5865F2

# Unicode fallback. Real custom emoji = assets/emojis/<key>.png + &syncemojis
DEFAULT_EMOJI = {
    "folder": "📂", "prefix": "✏️", "server": "🗄️", "latency": "📶", "gear": "⚙️",
    "question": "❓", "arrow": "▶️", "check": "✅", "links": "🔍", "tick": "✅",
    "cross": "❌", "warn": "⚠️",
    "antinuke": "🛡️", "moderation": "🔨", "automod": "🤖", "logger": "🧾", "utility": "⚙️",
    "join2create": "👤", "voice": "📢", "customrole": "👑", "welcomer": "💖", "ticket": "✉️",
    "music": "🎵", "custombot": "🧬", "noprefix": "🚀",
    "on": "🟢", "off": "🔴", "dot": "▫️", "list": "📜", "delete": "🗑️", "gift": "🎁", "clock": "⏰",
    "first": "⏮️", "prev": "◀️", "next": "▶️", "last": "⏭️", "mute": "🔇", "unmute": "🔊",
    "deafen": "🙉", "undeafen": "👂", "permit": "✅", "ban": "⛔", "transfer": "🔁",
    "play": "⏯️", "skip": "⏭️", "stop": "⏹️", "loop": "🔁", "shuffle": "🔀",
    "lock": "🔒", "unlock": "🔓", "hide": "🙈", "unhide": "👁️", "rename": "✏️",
    "limit": "👥", "claim": "👑", "info": "ℹ️",
}

# key: (Display name, emoji key, dropdown description, is_core)
# Cog class name = Display name without spaces
MODULES = {
    "antinuke":    ("AntiNuke",       "antinuke",    "Get All AntiNuke Command List", True),
    "moderation":  ("Moderation",     "moderation",  "Get All Moderation Command List", True),
    "automod":     ("AutoMod",        "automod",     "Get All Automod Command List", True),
    "logger":      ("Logger",         "logger",      "Get All Logger Command List", True),
    "utility":     ("Utility",        "utility",     "Get All Utility Command List", True),
    "join2create": ("Join To Create", "join2create", "Get All Join To Create Command List", False),
    "voice":       ("Voice",          "voice",       "Get All Voice Command List", False),
    "music":       ("Music",          "music",       "Get All Music Command List", False),
    "customrole":  ("Custom Role",    "customrole",  "Get All Custom Role Command List", False),
    "welcomer":    ("Welcomer",       "welcomer",    "Get All Welcomer Command List", False),
    "ticket":      ("Ticket",         "ticket",      "Get All Ticket Command List", False),
    "custombot":   ("Custom Bot",     "custombot",   "Get All Custom Bot Command List", False),
    "noprefix":    ("No Prefix",      "noprefix",    "Get All No Prefix Command List", False),
}
