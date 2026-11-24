import pathlib
import config

EMOJI = dict(config.DEFAULT_EMOJI)


def em(key: str) -> str:
    return EMOJI.get(key, "▫️")


async def load_app_emojis(bot) -> int:
    """Loads IDs from the Developer Portal Application Emojis (name = key)."""
    n = 0
    for e in await bot.fetch_application_emojis():
        if e.name in EMOJI:
            EMOJI[e.name] = str(e)
            n += 1
    return n


async def sync_assets(bot):
    """Uploads assets/emojis/*.png as Application Emojis."""
    folder = pathlib.Path("assets/emojis")
    existing = {e.name for e in await bot.fetch_application_emojis()}
    done, failed = [], []
    for f in sorted(folder.glob("*.*")):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp") or f.stem in existing:
            continue
        try:
            await bot.create_application_emoji(name=f.stem, image=f.read_bytes())
            done.append(f.stem)
        except Exception as ex:
            failed.append(f"{f.stem}: {ex}")
    await load_app_emojis(bot)
    return done, failed
