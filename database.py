import copy
import json

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (guild_id INTEGER PRIMARY KEY, prefix TEXT);
CREATE TABLE IF NOT EXISTS kv (guild_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (guild_id, key));
CREATE TABLE IF NOT EXISTS np_users (user_id INTEGER PRIMARY KEY, plan TEXT, expires INTEGER, added_by INTEGER);
CREATE TABLE IF NOT EXISTS np_claims (user_id INTEGER PRIMARY KEY, claimed_at INTEGER);
CREATE TABLE IF NOT EXISTS an_wl (guild_id INTEGER, target_id INTEGER, kind TEXT, filters TEXT,
    PRIMARY KEY (guild_id, target_id));
CREATE TABLE IF NOT EXISTS an_owners (guild_id INTEGER, user_id INTEGER, PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,
    user_id INTEGER, mod_id INTEGER, reason TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS afk (guild_id INTEGER, user_id INTEGER, reason TEXT, ts INTEGER,
    PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS customroles (guild_id INTEGER, user_id INTEGER, role_id INTEGER,
    PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS j2c_channels (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, owner_id INTEGER);
CREATE TABLE IF NOT EXISTS tickets (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, owner_id INTEGER,
    category TEXT, claimed_by INTEGER, status TEXT DEFAULT 'open', number INTEGER, created INTEGER);
"""


class Database:
    def __init__(self, path: str = "locus_v3.db"):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._kv: dict = {}

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def run(self, query: str, *args):
        cur = await self.conn.execute(query, args)
        await self.conn.commit()
        return cur

    async def one(self, query: str, *args):
        cur = await self.conn.execute(query, args)
        return await cur.fetchone()

    async def all(self, query: str, *args):
        cur = await self.conn.execute(query, args)
        return await cur.fetchall()

    async def val(self, query: str, *args):
        row = await self.one(query, *args)
        return row[0] if row else None

    # ---- JSON key/value config (per guild; gid 0 = global) ----
    async def kget(self, gid: int, key: str, default=None):
        k = (gid, key)
        if k not in self._kv:
            row = await self.one("SELECT value FROM kv WHERE guild_id=? AND key=?", gid, key)
            self._kv[k] = json.loads(row["value"]) if row else None
        v = self._kv[k]
        return copy.deepcopy(default if v is None else v)

    async def kset(self, gid: int, key: str, value):
        self._kv[(gid, key)] = copy.deepcopy(value)
        await self.run(
            "INSERT INTO kv VALUES(?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            gid, key, json.dumps(value))

    async def kdel(self, gid: int, key: str):
        self._kv.pop((gid, key), None)
        await self.run("DELETE FROM kv WHERE guild_id=? AND key=?", gid, key)

    async def close(self):
        if self.conn:
            await self.conn.close()
