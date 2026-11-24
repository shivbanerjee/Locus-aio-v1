# Locus (Nixo Devs)
Developed with ❤️ By Shiv / Ghost 🌷

Components V2 • Custom Emojis • SQLite • Lavalink Music • AntiNuke • AutoMod • VoiceMaster • Tickets • No Prefix • Custom Bot

## Setup
1. Install **Python 3.10+**.
2. `pip install -r requirements.txt` (discord.py **2.7.1+** is required for Components V2 and voice).
3. Copy `.env.example` to `.env` and fill in `TOKEN`, `CLIENT_ID`, `OWNER_IDS`, `SUPPORT_URL` (and `LAVALINK_*` for music).
4. Developer Portal → Bot → enable **Message Content**, **Server Members** and **Presence** intents.
5. `python main.py` (a new `locus_v3.db` database is created automatically).
6. Run the owner command `&sync` once to sync slash commands (music, ticket).

## Lavalink (music)
You need a Lavalink **v4** server with the **youtube-source plugin**. Put the host, port, password and SSL flag in `.env`.
Without Lavalink the rest of the bot works; only the music commands are disabled.

## Custom emojis
1. Upload emojis in the Developer Portal → Emojis, **or** put PNGs in `assets/emojis/` and run `&syncemojis`.
2. The emoji name must match the key (`antinuke`, `moderation`, `customrole` ...). Keys: `config.py` → `DEFAULT_EMOJI`.
3. Restart the bot. Any emoji that is missing falls back to a normal unicode emoji.

## Modules
- **AntiNuke** — `antinuke` (enable, disable, filters, wizard, punishment, logs, wl, unwl, wlist, wlreset), `extraowner`. 16 filters, instant punishment, auto-recovery.
- **Moderation** — kick, ban, unban, softban, fakeban, unbanall, mute, unmute, nick, warn, lock/unlock (+all), hide/unhide (+all), slowmode, nuke, snipe, `channel` group, `clear*` purge commands, `role` group, `rrole*`.
- **AutoMod** — `automod` (13 filters with a heat system, punishments, whitelist, blacklist, logging, rules).
- **Logger** — `logging` (setup, set, enable, disable, types, config, reset), 16 log types.
- **Utility** — afk, ping, stats, uptime, system, userinfo, serverinfo, roleinfo, channelinfo, avatar, banner, servericon, serverbanner, membercount, boostcount, joinedat, users, invite, prefix commands, ignore commands, `list` group.
- **Join To Create** — `voicemaster` (setup, buttons, config, limit, name, reset) with a 14-button interface.
- **Voice** — vcmute, vcunmute, vcdeafen, vcundeafen, vckick, vcmove, vcmoveall, vcmuteall, vcunmuteall.
- **Music** — join, play, skip, stop, pause, resume, volume, loop, shuffle, queue, nowplaying, 247, autoplay, remove, clearqueue, seek (prefix and slash).
- **Custom Role** — `customrole` create / rename / color / delete (boosters or Manage Roles).
- **Welcomer** — `greet` (setup, channel, type, message, content, title, description, color, thumbnail, image, deleteafter, autorole, test, config, variables, disable, reset).
- **Ticket** — `ticket` setup panel, Lock / Unlock / Claim / Close, Reopen / Transcript / Delete, `tclose`, `tdelete`, `tadd`, `tremove`, `ticketsync`.
- **Custom Bot** — `custombot` panel, `bbio`, `bpfp`, `bbanner`, `bnameplate`, `gnameplate` (owner).
- **No Prefix** — `np` check / add / remove / list / setup. Plans: 3d, 1w, 1m, 3m, life, plus a 7-day free-trial claim panel.

## Notes
- Keep the bot's role at the top of the role list, otherwise punishments and recovery will fail.
- Voice permissions (Move / Mute / Deafen Members) are checked at **server level**, so they work even when used from a text channel.
- The old `locus.db` is not migrated; the bot uses a new `locus_v3.db`.
