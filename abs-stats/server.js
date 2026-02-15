// abs-stats server (ESM)
// Your /app/package.json has "type": "module", so this file MUST use import syntax.

import express from "express";
import path from "path";
import { fileURLToPath } from "url";
import { Readable } from "stream";

// ===========================================================
// SECTION: App + env config
// ===========================================================
const app = express();

const PORT = Number(process.env.PORT || 3000);
const ABS_URL = String(process.env.ABS_URL || "http://audiobookshelf:80").replace(/\/+$/, "");
const ABS_TOKEN = process.env.ABS_TOKEN || (() => {
  // Fall back to the first token from ABS_TOKENS if ABS_TOKEN isn't set
  const raw = process.env.ABS_TOKENS || "";
  const first = raw.split(",").map(s => s.trim()).filter(Boolean)[0];
  if (first) {
    const idx = first.indexOf(":");
    return idx > -1 ? first.slice(idx + 1).trim() : first;
  }
  return undefined;
})();

// ADDRESS OF THE PYTHON ACHIEVEMENT ENGINE
// If running in Docker Bridge mode, change "localhost" to your container name
const ENGINE_URL = process.env.ENGINE_URL || "http://localhost:8000";

// ===========================================================
// SECTION: Username allowlist for public user endpoints
// ===========================================================
// Set ALLOWED_USERNAMES env var to a comma-separated list of usernames,
// or "*" to allow all users. If unset, all users are allowed.
function allowedUsernamesSet() {
  const raw = String(process.env.ALLOWED_USERNAMES || "").trim();
  if (!raw || raw === "*") return null; // null => allow all
  const list = raw.split(",").map(s => s.trim()).filter(Boolean);
  return new Set(list);
}

function parseUserTokens() {
  const raw = process.env.ABS_TOKENS || "";
  return raw
    .split(",")
    .map(s => s.trim())
    .filter(Boolean)
    .map(pair => {
      const idx = pair.indexOf(":");
      if (idx == -1) return null;
      const username = pair.slice(0, idx).trim();
      const token = pair.slice(idx + 1).trim();
      if (!username || !token) return null;
      return { username, token };
    })
    .filter(Boolean);
}

function formatAuthors(meta) {
  if (!meta) return "";
  if (typeof meta.author === "string" && meta.author.trim()) return meta.author.trim();
  const a = meta.authors;
  if (Array.isArray(a)) {
    const names = a
      .map(x => (typeof x === "string" ? x : (x?.name || x?.authorName || "")))
      .map(s => String(s || "").trim())
      .filter(Boolean);
    if (names.length) return names.join(", ");
  }
  if (a && typeof a === "object") {
    const name = a.name || a.authorName;
    if (name) return String(name).trim();
  }
  return "";
}

function buildFinishedSetFromMe(meJson) {
  const set = new Set();
  const mp = meJson?.mediaProgress;
  if (!Array.isArray(mp)) return set;
  for (const p of mp) {
    if (p && p.isFinished && p.libraryItemId) set.add(String(p.libraryItemId));
  }
  return set;
}

function buildFinishedMapFromMe(meJson) {
  const map = {};
  const mp = meJson?.mediaProgress;
  if (!Array.isArray(mp)) return map;
  for (const p of mp) {
    if (p && p.isFinished && p.libraryItemId) {
      const ts = p.finishedAt || p.finishedAtMs || p.finished_at || p.lastUpdate || p.updatedAt || Date.now();
      map[String(p.libraryItemId)] = Number(ts);
    }
  }
  return map;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.use(express.static(__dirname, { maxAge: "0", etag: false }));

if (!ABS_TOKEN) console.warn("WARNING: ABS_TOKEN is not set. ABS API calls will fail.");

function authHeaders(token = ABS_TOKEN) {
  return {
    Authorization: `Bearer ${token}`,
    "User-Agent": "abs-stats/1.0",
    Accept: "application/json",
  };
}

function safeNum(n, fallback = 0) {
  const x = Number(n);
  return Number.isFinite(x) ? x : fallback;
}
function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }
function toMinutesFromSeconds(sec) {
  const s = Number(sec);
  if (!Number.isFinite(s)) return 0;
  return s / 60;
}

function authorNamesFromSession(s) {
  const names = new Set();
  if (s?.displayAuthor) names.add(String(s.displayAuthor));
  const authors = s?.mediaMetadata?.authors;
  if (Array.isArray(authors)) for (const a of authors) if (a?.name) names.add(String(a.name));
  return [...names].filter(Boolean);
}
function addAuthorSeconds(map, authorName, seconds) {
  if (!authorName) return;
  const key = String(authorName).trim();
  if (!key) return;
  map.set(key, (map.get(key) || 0) + seconds);
}
function topAuthorFromSecondsMap(map) {
  let bestName = null, bestSeconds = 0;
  for (const [name, sec] of map.entries()) {
    if (sec > bestSeconds) { bestSeconds = sec; bestName = name; }
  }
  return bestName ? { name: bestName, minutes: bestSeconds / 60 } : null;
}

async function absJson(apiPath, token = ABS_TOKEN) {
  const url = `${ABS_URL}${apiPath}`;
  const r = await fetch(url, { headers: authHeaders(token) });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`ABS ${r.status} ${r.statusText} for ${apiPath} :: ${text.slice(0, 200)}`);
  }
  return await r.json();
}

async function absStream(apiPath, res, token = ABS_TOKEN) {
  const url = `${ABS_URL}${apiPath}`;
  const r = await fetch(url, { headers: authHeaders(token) });
  if (!r.ok || !r.body) {
    const text = await r.text().catch(() => "");
    res.status(r.status || 500).send(text || "stream_failed");
    return;
  }
  const ct = r.headers.get("content-type");
  if (ct) res.setHeader("content-type", ct);
  try {
    Readable.fromWeb(r.body).pipe(res);
  } catch {
    const buf = Buffer.from(await r.arrayBuffer());
    res.end(buf);
  }
}

async function getListeningSessions(userId, opts = {}) {
  const itemsPerPage = opts.itemsPerPage || 200;
  const maxPages = opts.maxPages || 25;
  const token = opts.token || ABS_TOKEN;
  let page = 0;
  let all = [];
  while (page < maxPages) {
    const data = await absJson(`/api/users/${encodeURIComponent(userId)}/listening-sessions?itemsPerPage=${itemsPerPage}&page=${page}`, token);
    const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
    if (!sessions.length) break;
    all = all.concat(sessions);
    page += 1;
  }
  return all;
}

function computeCurrentlyReading(sessions) {
  const sorted = [...sessions].sort((a,b) => safeNum(b.updatedAt,0) - safeNum(a.updatedAt,0));
  for (const s of sorted) {
    const duration = safeNum(s.duration, 0);
    const currentTime = safeNum(s.currentTime, 0);
    if (duration <= 0) continue;
    const progress = clamp(currentTime / duration, 0, 1);
    if (progress < 0.01) continue;
    if (progress >= 0.98) continue;
    if (!s.libraryItemId) continue;
    return {
      libraryItemId: s.libraryItemId,
      progress,
      currentTime,
      duration,
      lastUpdate: safeNum(s.updatedAt, 0) || safeNum(s.startedAt, 0),
      title: s.displayTitle || s.mediaMetadata?.title || "",
      subtitle: s.mediaMetadata?.subtitle || "",
      authorText: (s.displayAuthor || (s.mediaMetadata?.authors || []).map(a => a?.name).filter(Boolean).join(", ") || ""),
      lastSession: {
        startedAt: safeNum(s.startedAt, 0),
        updatedAt: safeNum(s.updatedAt, 0),
        timeListening: safeNum(s.timeListening, 0),
        device: (s.deviceInfo?.clientName || s.deviceInfo?.osName || "")
      },
      coverUrl: `api/cover/${encodeURIComponent(s.libraryItemId)}`
    };
  }
  return null;
}

function computeLastFinished(sessions) {
  const sorted = [...sessions].sort((a,b) => safeNum(b.updatedAt,0) - safeNum(a.updatedAt,0));
  for (const s of sorted) {
    const duration = safeNum(s.duration, 0);
    const currentTime = safeNum(s.currentTime, 0);
    if (duration <= 0) continue;
    const progress = clamp(currentTime / duration, 0, 1);
    const finished = progress >= 0.985 || currentTime >= (duration - 30);
    if (!finished) continue;
    if (!s.libraryItemId) continue;
    return {
      libraryItemId: s.libraryItemId,
      finishedAt: safeNum(s.updatedAt, 0) || safeNum(s.startedAt, 0),
      duration,
      title: s.displayTitle || s.mediaMetadata?.title || "",
      subtitle: s.mediaMetadata?.subtitle || "",
      authorText: (s.displayAuthor || (s.mediaMetadata?.authors || []).map(a => a?.name).filter(Boolean).join(", ") || ""),
      coverUrl: `api/cover/${encodeURIComponent(s.libraryItemId)}`
    };
  }
  return null;
}

function sumTimeListeningSecondsForRange(sessions, startMsInclusive) {
  let sum = 0;
  for (const s of sessions) {
    const startedAt = safeNum(s.startedAt, 0);
    if (startedAt >= startMsInclusive) sum += safeNum(s.timeListening, 0);
  }
  return sum;
}

function startOfUtcYearMs(nowMs) {
  const d = new Date(nowMs);
  const y = d.getUTCFullYear();
  return Date.UTC(y, 0, 1, 0, 0, 0, 0);
}

app.get("/health", (req, res) => res.json({ ok: true }));

app.get("/api/cover/:libraryItemId", async (req, res) => {
  try {
    await absStream(`/api/items/${encodeURIComponent(req.params.libraryItemId)}/cover`, res);
  } catch {
    res.status(500).send("cover_failed");
  }
});

app.get("/api/users", async (req, res) => {
  try {
    const now = Date.now();
    const since7Ms = now - 7 * 24 * 60 * 60 * 1000;
    const since30Ms = now - 30 * 24 * 60 * 60 * 1000;
    const yearStartMs = startOfUtcYearMs(now);
    const allowed = allowedUsernamesSet();
    const udata = await absJson("/api/users");
    const users = Array.isArray(udata?.users) ? udata.users : [];
    const activeUsers = users.filter(u => u?.id && u?.username).filter(u => !allowed || allowed.has(u.username));
    const out = [];

    for (const u of activeUsers) {
      let lifetimeMinutes = 0;
      let topAuthorLifetime = null;
      try {
        const stats = await absJson(`/api/users/${encodeURIComponent(u.id)}/listening-stats`);
        lifetimeMinutes = toMinutesFromSeconds(stats?.totalTime ?? 0);
        const items = stats?.items && typeof stats.items === "object" ? stats.items : {};
        const authorSeconds = new Map();
        for (const k of Object.keys(items)) {
          const it = items[k];
          const sec = safeNum(it?.timeListening, 0);
          if (sec <= 0) continue;
          const authors = it?.mediaMetadata?.authors;
          const name = Array.isArray(authors) && authors.length ? authors[0]?.name : null;
          addAuthorSeconds(authorSeconds, name, sec);
        }
        topAuthorLifetime = topAuthorFromSecondsMap(authorSeconds);
      } catch {
        lifetimeMinutes = 0;
        topAuthorLifetime = null;
      }

      let sessions = [];
      try {
        sessions = await getListeningSessions(u.id, { itemsPerPage: 200, maxPages: 25 });
      } catch {
        sessions = [];
      }

      const last7Seconds = sumTimeListeningSecondsForRange(sessions, since7Ms);
      const last30Seconds = sumTimeListeningSecondsForRange(sessions, since30Ms);
      const yearSeconds = sumTimeListeningSecondsForRange(sessions, yearStartMs);
      const avgDaily30Minutes = (last30Seconds / 60) / 30;

      const ytdAuthorSeconds = new Map();
      for (const s of sessions) {
        const startedAt = safeNum(s.startedAt, 0);
        if (startedAt < yearStartMs) continue;
        const sec = safeNum(s.timeListening, 0);
        if (sec <= 0) continue;
        const names = authorNamesFromSession(s);
        if (!names.length) continue;
        addAuthorSeconds(ytdAuthorSeconds, names[0], sec);
      }
      const topAuthorYTD = topAuthorFromSecondsMap(ytdAuthorSeconds);

      out.push({
        id: u.id,
        username: u.username,
        lastSeen: safeNum(u.lastSeen, 0),
        lifetimeMinutes,
        last7Minutes: last7Seconds / 60,
        yearSeconds,
        avgDaily30Minutes,
        topAuthorYTD,
        topAuthorLifetime,
        currentlyReading: computeCurrentlyReading(sessions),
        lastFinished: computeLastFinished(sessions),
      });
    }

    res.json({ updatedAt: new Date().toISOString(), users: out });
  } catch (e) {
    res.status(500).json({ message: "backend_failed", error: String(e?.message || e) });
  }
});

app.get("/api/usernames", async (req, res) => {
  try {
    const allowed = allowedUsernamesSet();
    const udata = await absJson("/api/users");
    const users = Array.isArray(udata?.users) ? udata.users : [];
    const filtered = users
      .filter(u => u?.id && u?.username)
      .filter(u => !allowed || allowed.has(u.username))
      .map(u => ({
        id: String(u.id),
        username: String(u.username),
        lastSeen: safeNum(u.lastSeen, 0),
      }))
      .sort((a, b) => a.username.localeCompare(b.username));
    const map = {};
    for (const u of filtered) map[u.id] = u.username;
    res.json({ updatedAt: new Date().toISOString(), users: filtered, map });
  } catch (err) {
    res.status(500).json({ error: "backend_failed", message: String(err?.message || err) });
  }
});

app.get("/api/playlists", async (req, res) => {
  try {
    const userTokens = parseUserTokens();
    if (userTokens.length) {
      const results = await Promise.all(
        userTokens.map(async ({ username: label, token }) => {
          const me = await absJson("/api/me", token);
          const playlistsData = await absJson("/api/playlists", token);
          const finishedSet = buildFinishedSetFromMe(me);
          const playlists = Array.isArray(playlistsData?.playlists)
            ? playlistsData.playlists
            : Array.isArray(playlistsData)
              ? playlistsData
              : [];
          const normalized = playlists.map((pl) => {
            const items = Array.isArray(pl.items) ? pl.items : [];
            const liteItems = items.map((it) => {
              const li = it.libraryItem || it.libraryItemExpanded || it.libraryItem || null;
              const meta = li?.media?.metadata || li?.mediaMetadata || it?.mediaMetadata || {};
              const title = meta?.title || it?.title || li?.title || "Unknown title";
              const author = formatAuthors(meta) || it?.author || li?.author || "";
              const libraryItemId = li?.id || it?.libraryItemId || it?.libraryItemId || null;
              return {
                libraryItemId,
                title,
                author,
                finished: libraryItemId ? finishedSet.has(libraryItemId) : false,
                coverUrl: libraryItemId ? `api/cover/${encodeURIComponent(libraryItemId)}` : null,
              };
            });
            return {
              id: pl.id,
              name: pl.name,
              description: pl.description,
              updatedAt: pl.updatedAt || pl.updated_at || null,
              createdAt: pl.createdAt || pl.created_at || null,
              itemCount: pl.items?.length ?? pl.itemCount ?? liteItems.length ?? 0,
              items: liteItems,
            };
          });
          return {
            userId: me?.id || null,
            username: me?.username || label || "unknown",
            playlists: normalized,
          };
        })
      );
      const users = results.filter((u) => (u.userId || u.username) && Array.isArray(u.playlists));
      users.sort((a, b) => String(a.username).localeCompare(String(b.username)));
      res.json({ updatedAt: new Date().toISOString(), users });
      return;
    }

    const data = await absJson("/api/playlists");
    const playlists = Array.isArray(data?.playlists)
      ? data.playlists
      : Array.isArray(data)
        ? data
        : [];
    const usersMap = new Map();
    for (const pl of playlists) {
      const uid = pl.userId || pl.user_id || "unknown";
      if (!usersMap.has(uid)) {
        usersMap.set(uid, { userId: uid, username: "unknown", playlists: [] });
      }
      usersMap.get(uid).playlists.push(pl);
    }
    try {
      const absUsers = await absJson("/api/users");
      const idToName = new Map((absUsers || []).map((u) => [u.id, u.username]));
      for (const u of usersMap.values()) {
        if (idToName.has(u.userId)) u.username = idToName.get(u.userId);
      }
    } catch (_) {}
    res.json({ updatedAt: new Date().toISOString(), users: Array.from(usersMap.values()) });
  } catch (err) {
    console.error("Error in /api/playlists:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/completed", async (req, res) => {
  try {
    const userTokens = parseUserTokens();
    if (userTokens.length) {
      const results = await Promise.all(
        userTokens.map(async ({ username: label, token }) => {
          const me = await absJson("/api/me", token);
          const finishedMap = buildFinishedMapFromMe(me);
          return {
            userId: me?.id || null,
            username: me?.username || label || "unknown",
            finishedIds: Object.keys(finishedMap),
            finishedDates: finishedMap,
            finishedCount: Object.keys(finishedMap).length,
          };
        })
      );
      const users = results.filter((u) => u.userId || u.username);
      users.sort((a, b) => String(a.username).localeCompare(String(b.username)));
      res.json({ updatedAt: new Date().toISOString(), users });
      return;
    }
    const me = await absJson("/api/me");
    const finishedMap = buildFinishedMapFromMe(me);
    res.json({
      updatedAt: new Date().toISOString(),
      users: [
        {
          userId: me?.id || "unknown",
          username: me?.username || "unknown",
          finishedIds: Object.keys(finishedMap),
          finishedDates: finishedMap,
          finishedCount: Object.keys(finishedMap).length,
        },
      ],
    });
  } catch (err) {
    console.error("Error in /api/completed:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});

async function getAllLibraryItems(libraryId) {
  const limit = 200;
  let page = 0;
  const out = [];
  while (true) {
    const data = await absJson(`/api/libraries/${encodeURIComponent(libraryId)}/items?limit=${limit}&page=${page}`);
    const batch = Array.isArray(data?.items) ? data.items : (Array.isArray(data?.results) ? data.results : []);
    if (!batch.length) break;
    out.push(...batch);
    page += 1;
    if (page > 500) break;
  }
  return out;
}

app.get("/api/series", async (req, res) => {
  try {
    const search = String(req.query.search || "").trim().toLowerCase();
    const libsResp = await absJson("/api/libraries");
    const libraries = Array.isArray(libsResp?.libraries) ? libsResp.libraries : [];
    const seriesMap = new Map();
    for (const lib of libraries) {
      if (lib?.mediaType !== "book") continue;
      const seriesList = await getAllSeriesForLibrary(lib.id);
      for (const s of seriesList) {
        const seriesId = String(s?.id || "");
        const seriesName = String(s?.name || "");
        if (!seriesId || !seriesName) continue;
        const mode = String(req.query.mode || "contains").toLowerCase();
        if (search) {
          const n = seriesName.toLowerCase();
          if (mode === "exact") {
            if (n !== search) continue;
          } else {
            if (!n.includes(search)) continue;
          }
        }
        const books = Array.isArray(s?.books) ? s.books : [];
        seriesMap.set(seriesId, {
          seriesId,
          seriesName,
          bookCount: books.length,
          books: books
            .map(b => {
              const li = b?.libraryItem || b;
              const meta = li?.media?.metadata || {};
              return {
                libraryItemId: li?.id || b?.libraryItemId || null,
                title: meta?.title || li?.title || b?.title || "Unknown title",
                sequence: meta?.seriesSequence ?? b?.sequence ?? null,
              };
            })
            .filter(x => x.libraryItemId)
            .sort((a, b) => (a.sequence ?? 9999) - (b.sequence ?? 9999)),
        });
      }
    }
    const series = Array.from(seriesMap.values())
      .filter(s => s.bookCount > 0)
      .sort((a, b) => a.seriesName.localeCompare(b.seriesName));
    res.json({ updatedAt: new Date().toISOString(), series });
  } catch (err) {
    console.error("Error in /api/series:", err);
    res.status(500).json({ error: "Failed to load series list", message: err?.message || String(err) });
  }
});

async function getAllSeriesForLibrary(libraryId) {
  const limit = 200;
  let page = 0;
  const out = [];
  while (true) {
    const data = await absJson(`/api/libraries/${encodeURIComponent(libraryId)}/series?limit=${limit}&page=${page}`);
    const batch = Array.isArray(data?.results) ? data.results : [];
    if (!batch.length) break;
    out.push(...batch);
    page += 1;
    if (page > 500) break;
  }
  return out;
}

app.get("/api/series/:id", async (req, res) => {
  try {
    const id = String(req.params.id || "");
    if (!id) return res.status(400).json({ error: "Missing series id" });
    const libsResp = await absJson("/api/libraries");
    const libraries = Array.isArray(libsResp?.libraries) ? libsResp.libraries : [];
    for (const lib of libraries) {
      if (lib?.mediaType !== "book") continue;
      const data = await absJson(`/api/libraries/${encodeURIComponent(lib.id)}/series?limit=200&page=0`);
      const batch = Array.isArray(data?.results) ? data.results : [];
      const hit = batch.find(s => String(s?.id || "") === id);
      if (hit) {
        const books = Array.isArray(hit?.books) ? hit.books : [];
        return res.json({
          updatedAt: new Date().toISOString(),
          series: {
            seriesId: String(hit.id),
            seriesName: String(hit.name || ""),
            bookCount: books.length,
            books: books.map(b => {
              const li = b?.libraryItem || b;
              const meta = li?.media?.metadata || {};
              return {
                libraryItemId: li?.id || b?.libraryItemId || null,
                title: meta?.title || li?.title || b?.title || "Unknown title",
                sequence: meta?.seriesSequence ?? b?.sequence ?? null,
              };
            }).filter(x => x.libraryItemId)
          }
        });
      }
    }
    res.status(404).json({ error: "Series not found", seriesId: id });
  } catch (err) {
    console.error("Error in /api/series/:id:", err);
    res.status(500).json({ error: "Failed", message: err?.message || String(err) });
  }
});

app.get("/api/item/:id", async (req, res) => {
  try {
    const id = String(req.params.id || "").trim();
    if (!id) return res.status(400).json({ error: "Missing libraryItemId" });
    const item = await absJson(`/api/items/${encodeURIComponent(id)}`);
    const meta = item?.media?.metadata || {};
    const authors = Array.isArray(meta.authors) ? meta.authors.map(a => a.name).filter(Boolean) : meta.authorName ? [meta.authorName] : meta.author ? [meta.author] : [];
    let narrators = [];
    if (Array.isArray(meta.narrators)) {
      narrators = meta.narrators.map(n => n.name || n).filter(Boolean);
    } else if (meta.narrator) {
      narrators = [meta.narrator];
    }
    if (!narrators.length && Array.isArray(item?.media?.tracks)) {
      const trackNarrators = item.media.tracks.map(t => t?.performer || t?.metadata?.performer || null).filter(Boolean);
      narrators = [...new Set(trackNarrators)];
    }

    const audioFiles = item?.media?.audioFiles || [];
    const duration = audioFiles.reduce((sum, f) => sum + (f.duration || 0), 0);
    res.json({
      libraryItemId: id,
      title: meta.title || item?.title || "Unknown title",
      authors,
      narrators,
      duration,
    });

  } catch (err) {
    console.error("Error in /api/item/:id:", err);
    res.status(500).json({ error: "Failed to load item" });
  }
});
app.get("/api/user-books/:userId", async (req, res) => {
  try {
    const userId = String(req.params.userId || "").trim();
    if (!userId) return res.status(400).json({ error: "Missing userId" });

    const userTokens = parseUserTokens();
    let token = null;
    let me = null;

    if (userTokens.length) {
      for (const ut of userTokens) {
        const meCheck = await absJson("/api/me", ut.token);
        if (meCheck?.id === userId) {
          token = ut.token;
          me = meCheck;
          break;
        }
      }
    }
    if (!me) me = await absJson("/api/me", token);

    const finishedMap = buildFinishedMapFromMe(me);
    const finishedIds = Object.keys(finishedMap);

    const books = [];
    for (const id of finishedIds) {
      try {
        const item = await absJson(`/api/items/${encodeURIComponent(id)}`, token);
        const meta = item?.media?.metadata || {};
        const audioFiles = item?.media?.audioFiles || [];
        const durationSec = audioFiles.reduce((sum, f) => sum + (f.duration || 0), 0);
        books.push({
          libraryItemId: id,
          title: meta.title || item?.title || "Unknown",
          authors: Array.isArray(meta.authors) ? meta.authors.map(a => a.name).filter(Boolean) : [],
          durationSeconds: Math.round(durationSec),
          durationHours: +(durationSec / 3600).toFixed(2),
          finishedAt: finishedMap[id] || null,
        });
      } catch (e) {
        books.push({ libraryItemId: id, title: "FETCH_ERROR", durationSeconds: 0, durationHours: 0 });
      }
    }

    books.sort((a, b) => (b.durationHours || 0) - (a.durationHours || 0));

    const totalSec = books.reduce((sum, b) => sum + (b.durationSeconds || 0), 0);
    res.json({
      userId,
      username: me?.username || "unknown",
      finishedCount: books.length,
      totalBookDurationSeconds: totalSec,
      totalBookDurationHours: +(totalSec / 3600).toFixed(2),
      books,
    });
  } catch (err) {
    console.error("Error in /api/user-books/:userId:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});
app.get("/api/listening-sessions", async (req, res) => {
  try {
    const userTokens = parseUserTokens();

    if (userTokens.length) {
      const results = await Promise.all(
        userTokens.map(async ({ username: label, token }) => {
          const me = await absJson("/api/me", token);
          const userId = me?.id || null;
          const sessionsRaw = userId ? await getListeningSessions(userId) : [];
          const sessions = sessionsRaw.map((s) => ({
            id: s.id || s.sessionId || null,
            libraryItemId: s.libraryItemId || s.library_item_id || s.mediaItemId || null,
            startedAt: s.startedAt || s.startTime || s.started_at || null,
            endedAt: s.endedAt || s.endTime || s.ended_at || null,
            updatedAt: s.updatedAt || s.updated_at || null,
            duration: s.duration || s.listenDuration || s.listen_duration || null,
            timeListening: s.timeListening || 0,
            device: s.device || null,
          }));
          return {
            userId,
            username: me?.username || label || "unknown",
            sessions,
            sessionCount: sessions.length,
          };
        })
      );
      const users = results.filter((u) => (u.userId || u.username));
      users.sort((a, b) => String(a.username).localeCompare(String(b.username)));
      res.json({ updatedAt: new Date().toISOString(), users });
      return;
    }

    const me = await absJson("/api/me");
    const userId = me?.id || null;
    const sessionsRaw = userId ? await getListeningSessions(userId) : [];
    const sessions = sessionsRaw.map((s) => ({
      id: s.id || s.sessionId || null,
      libraryItemId: s.libraryItemId || s.library_item_id || s.mediaItemId || null,
      startedAt: s.startedAt || s.startTime || s.started_at || null,
      endedAt: s.endedAt || s.endTime || s.ended_at || null,
      updatedAt: s.updatedAt || s.updated_at || null,
      duration: s.duration || s.listenDuration || s.listen_duration || null,
      device: s.device || null,
    }));
    res.json({
      updatedAt: new Date().toISOString(),
      users: [
        {
          userId: userId || "unknown",
          username: me?.username || "unknown",
          sessions,
          sessionCount: sessions.length,
        },
      ],
    });
  } catch (err) {
    console.error("Error in /api/listening-sessions:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/listening-time", async (req, res) => {
  try {
    const userTokens = parseUserTokens();
    async function getUserTotalTime(userId, token) {
      try {
        const stats = await absJson(`/api/users/${userId}/listening-stats`, token);
        return stats?.totalTime || 0;
      } catch (err) {
        return 0;
      }
    }
    if (userTokens.length) {
      const results = await Promise.all(
        userTokens.map(async ({ username: label, token }) => {
          const me = await absJson("/api/me", token);
          const listeningSeconds = await getUserTotalTime(me.id, token);
          return {
            userId: me?.id || null,
            username: me?.username || label || "unknown",
            listeningSeconds,
            listeningHours: listeningSeconds / 3600.0,
            sessionCount: 0,
          };
        })
      );
      const users = results.filter((u) => (u.userId || u.username));
      users.sort((a, b) => String(a.username).localeCompare(String(b.username)));
      res.json({ updatedAt: new Date().toISOString(), users });
      return;
    }
    const me = await absJson("/api/me");
    const listeningSeconds = await getUserTotalTime(me.id, ABS_TOKEN);
    res.json({
      updatedAt: new Date().toISOString(),
      users: [
        {
          userId: me?.id || "unknown",
          username: me?.username || "unknown",
          listeningSeconds,
          listeningHours: listeningSeconds / 3600.0,
          sessionCount: 0,
        },
      ],
    });
  } catch (err) {
    console.error("Error in /api/listening-time:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/leaderboard", async (req, res) => {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/api/users`);
    if (!r.ok) throw new Error(`local /api/users -> ${r.status}`);
    const data = await r.json();
    const users = Array.isArray(data?.users) ? data.users : [];
    const rows = users
      .map(u => ({
        id: u.id,
        username: u.username,
        lifetimeMinutes: safeNum(u.lifetimeMinutes, 0),
        last7Minutes: safeNum(u.last7Minutes, 0),
        avgDaily30Minutes: safeNum(u.avgDaily30Minutes, 0),
        lastSeen: u.lastSeen ?? null
      }))
      .sort((a, b) => b.lifetimeMinutes - a.lifetimeMinutes);
    res.json({ updatedAt: new Date().toISOString(), users: rows });
  } catch (err) {
    console.error("Error in /api/leaderboard:", err);
    res.status(500).json({ error: "backend_failed" });
  }
});

// ===========================================================
// SECTION: Achievement Engine Support Endpoints
// ===========================================================

async function tokenForUserId(userId) {
  const userTokens = parseUserTokens();
  if (!userId) return ABS_TOKEN;
  if (userTokens.length) {
    try {
      const udata = await absJson("/api/users");
      const users = Array.isArray(udata?.users) ? udata.users : (Array.isArray(udata) ? udata : []);
      const u = users.find(x => String(x?.id) === String(userId));
      const uname = u?.username ? String(u.username) : null;
      if (uname) {
        const hit = userTokens.find(t => String(t.username).toLowerCase() === uname.toLowerCase());
        if (hit?.token) return hit.token;
      }
    } catch (e) {}
  }
  return ABS_TOKEN;
}

function epochMs(v) {
  if (v == null) return null;
  if (typeof v === "number") return v;
  const s = String(v).trim();
  if (!s) return null;
  const n = Number(s);
  if (Number.isFinite(n)) return n;
  const d = Date.parse(s);
  return Number.isFinite(d) ? d : null;
}

function dayKeyLocal(ms) {
  const d = new Date(ms);
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,"0");
  const da = String(d.getDate()).padStart(2,"0");
  return `${y}-${m}-${da}`;
}

function isWeekendLocal(ms) {
  const dow = new Date(ms).getDay();
  return dow === 0 || dow === 6;
}

app.get("/api/users/:userId/completions", async (req, res) => {
  try {
    const userId = String(req.params.userId || "").trim();
    const after = epochMs(req.query.after);
    const token = await tokenForUserId(userId);
    const me = await absJson("/api/me", token);
    if (userId && me?.id && String(me.id) !== userId) {
      return res.status(403).json({ error: "user_mismatch" });
    }
    const mp = Array.isArray(me?.mediaProgress) ? me.mediaProgress : [];
    const completions = mp
      .filter(p => p?.isFinished && p?.libraryItemId)
      .map(p => {
        const finishedAt = epochMs(p?.finishedAt ?? p?.finishedAtMs ?? p?.finished_at ?? null)
          ?? epochMs(p?.progressLastUpdate ?? p?.lastUpdate ?? p?.updatedAt ?? p?.updated_at ?? null);
        return {
          libraryItemId: String(p.libraryItemId),
          finishedAt: finishedAt,
          progressLastUpdate: epochMs(p?.progressLastUpdate ?? null)
        };
      })
      .filter(x => !after || (x.finishedAt && x.finishedAt > after));
    res.json({ updatedAt: new Date().toISOString(), userId: me?.id || userId || null, completionsCount: completions.length, completions });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/users/:userId/streaks", async (req, res) => {
  try {
    const userId = String(req.params.userId || "").trim();
    const token = await tokenForUserId(userId);
    const me = await absJson("/api/me", token);
    if (userId && me?.id && String(me.id) !== userId) return res.status(403).json({ error: "user_mismatch" });

    const since = req.query.since || null;
    const limit = req.query.limit || null;
    const candidatePaths = [
      "/api/me/listening-sessions",
      "/api/me/listeningSessions",
      "/api/listening-sessions",
      "/api/listeningSessions",
    ];
    let sessionsRaw = [];
    for (const path of candidatePaths) {
      try {
        let fullPath = path;
        const qs = [];
        if (since) qs.push(`since=${encodeURIComponent(since)}`);
        if (limit) qs.push(`limit=${encodeURIComponent(limit)}`);
        if (qs.length) fullPath = `${path}?${qs.join("&")}`;
        const data = await absJson(fullPath, token);
        sessionsRaw = Array.isArray(data?.sessions) ? data.sessions : Array.isArray(data) ? data : Array.isArray(data?.listeningSessions) ? data.listeningSessions : [];
        if(sessionsRaw.length) break;
      } catch (e) {}
    }

    const daySet = new Set();
    for (const s of sessionsRaw) {
      const ts = epochMs(s?.endedAt ?? s?.updatedAt ?? s?.startedAt);
      if (ts) daySet.add(dayKeyLocal(ts));
    }
    const days = Array.from(daySet).sort();
    let longest = 0, run = 0;
    for (let i = 0; i < days.length; i++) {
      if (i === 0) { run = 1; continue; }
      const prev = new Date(days[i-1]+"T00:00:00").getTime();
      const now = new Date(days[i]+"T00:00:00").getTime();
      if (Math.round((now - prev) / 86400000) === 1) run += 1;
      else run = 1;
      if (run > longest) longest = run;
    }
    res.json({ userId: me?.id, longestStreakDays: Math.max(longest, run) });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/users/:userId/listening-windows", async (req, res) => {
  try {
    const userId = String(req.params.userId || "").trim();
    const from = epochMs(req.query.from);
    const to = epochMs(req.query.to);
    if (!from || !to) return res.status(400).json({ error: "missing_from_to" });

    const token = await tokenForUserId(userId);
    const me = await absJson("/api/me", token);

    // Fetch sessions
    const candidatePaths = ["/api/me/listening-sessions", "/api/me/listeningSessions"];
    let sessionsRaw = [];
    for (const path of candidatePaths) {
      try {
        const data = await absJson(path, token);
        sessionsRaw = Array.isArray(data?.sessions) ? data.sessions : [];
        if(sessionsRaw.length) break;
      } catch (e) {}
    }

    let weekendSeconds = 0;
    let lateNightSeconds = 0;
    let longSessionCount = 0;
    let sessionCount = 0;

    for (const s of sessionsRaw) {
      const ts = epochMs(s?.startedAt || s?.endedAt);
      if (!ts || ts < from || ts > to) continue;

      const dur = safeNum(s?.duration || s?.listenDuration || 0);
      sessionCount++;
      if (dur >= 7200) longSessionCount++;

      const h = new Date(ts).getHours();
      if (h >= 0 && h < 5) lateNightSeconds += dur;
      if (isWeekendLocal(ts)) weekendSeconds += dur;
    }

    res.json({
      userId: me.id,
      window: { from, to },
      sessionCount,
      weekendSeconds,
      lateNightSeconds,
      longSessionCount
    });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/users/:userId/achievement-progress", async (req, res) => {
  try {
    const userId = String(req.params.userId || "").trim();
    const token = await tokenForUserId(userId);
    const me = await absJson("/api/me", token);

    const mp = Array.isArray(me?.mediaProgress) ? me.mediaProgress : [];
    const finishedCount = mp.filter(p => p?.isFinished).length;

    let listenStats = {};
    try {
      listenStats = await absJson(`/api/users/${userId}/listening-stats`, token);
    } catch {}
    const listeningSeconds = safeNum(listenStats?.totalTime || 0);
    const hours = listeningSeconds / 3600;

    const milestonesBooks = [5,10,25,50,100,500];
    const milestonesHours = [10,50,100,500,1000];

    function nextTarget(curr, arr) {
      for(const t of arr) if(curr < t) return t;
      return null;
    }

    res.json({
      userId: me.id,
      metrics: { finishedCount, listeningSeconds, listeningHours: hours },
      nextUp: {
        books: { current: finishedCount, target: nextTarget(finishedCount, milestonesBooks) },
        hours: { current: Math.round(hours), target: nextTarget(hours, milestonesHours) }
      }
    });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/series-hours", async (req, res) => {
  try {
    const base = "http://127.0.0.1:" + PORT;
    const s = await (await fetch(base + "/api/series")).json();
    const seriesList = Array.isArray(s?.series) ? s.series : [];
    const durCache = new Map();

    async function durSec(id) {
      if (durCache.has(id)) return durCache.get(id);
      try {
        const item = await absJson(`/api/items/${encodeURIComponent(id)}`);
        const sec = item?.media?.duration || item?.duration || 0;
        durCache.set(id, sec);
        return sec;
      } catch { return 0; }
    }

    const out = [];
    for (const s of seriesList) {
      let seconds = 0;
      for (const b of (s.books || [])) {
        if (b.libraryItemId) seconds += await durSec(b.libraryItemId);
      }
      out.push({
        seriesId: s.seriesId,
        seriesName: s.seriesName,
        bookCount: s.bookCount,
        totalDurationSeconds: seconds,
        totalHours: Math.round((seconds/3600)*100)/100
      });
    }
    res.json({ series: out });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/series/:seriesId/books", async (req, res) => {
  try {
    const sid = req.params.seriesId;
    const base = "http://127.0.0.1:" + PORT;
    const s = await (await fetch(base + "/api/series/" + encodeURIComponent(sid))).json();
    const books = s?.series?.books || [];

    const out = [];
    for (const b of books) {
      const id = b.libraryItemId;
      try {
        const item = await absJson(`/api/items/${encodeURIComponent(id)}`);
        const sec = item?.media?.duration || 0;
        out.push({
          libraryItemId: id,
          title: b.title,
          sequence: b.sequence,
          durationSeconds: sec,
          durationHours: sec/3600
        });
      } catch {}
    }
    res.json({ seriesId: sid, books: out });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

app.get("/api/catalog", async (req, res) => {
  try {
    const u = await absJson("/api/users");
    const users = Array.isArray(u?.users) ? u.users : [];
    const s = await absJson("/api/libraries");
    const libs = Array.isArray(s?.libraries) ? s.libraries : [];
    res.json({
      users: users.map(x => ({ id: x.id, username: x.username })),
      libraries: libs.map(l => ({ id: l.id, name: l.name }))
    });
  } catch (err) {
    res.status(500).json({ error: "backend_failed" });
  }
});

// ===========================================================
// SECTION: Proxy to Python Engine (CONNECTS DASHBOARD TO AWARDS)
// ===========================================================
async function proxyToEngine(req, res, path) {
  try {
    const r = await fetch(`${ENGINE_URL}${path}`);
    if (!r.ok) throw new Error(`Engine returned ${r.status}`);
    const data = await r.json();
    res.json(data);
  } catch (err) {
    console.error(`Proxy Error (${path}):`, err.message);
    if (path.includes("awards")) res.json({ users: [] });
    else if (path.includes("definitions")) res.json({ achievements: [] });
    else if (path.includes("progress")) res.json({ users: [] });
    else res.status(502).json({ error: "engine_unavailable" });
  }
}

app.get("/api/awards", (req, res) => proxyToEngine(req, res, "/api/awards"));
app.get("/api/definitions", (req, res) => proxyToEngine(req, res, "/api/definitions"));
app.get("/api/progress", (req, res) => proxyToEngine(req, res, "/api/progress"));

// --- Discord webhook proxy (achievement-engine -> abs-stats -> Discord) ---
app.post("/api/discord-notify", express.json(), async (req, res) => {
  const webhookUrl = process.env.DISCORD_WEBHOOK_URL;
  if (!webhookUrl) return res.status(500).json({ error: "DISCORD_WEBHOOK_URL not set" });
  try {
    const payload = JSON.stringify(req.body);
    const url = new URL(webhookUrl);
    const mod = url.protocol === "https:" ? await import("https") : await import("http");
    const r = await new Promise((resolve, reject) => {
      const rq = mod.default.request(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) },
      }, resolve);
      rq.on("error", reject);
      rq.write(payload);
      rq.end();
    });
    let body = "";
    for await (const chunk of r) body += chunk;
    res.status(r.statusCode).send(body || "ok");
  } catch (e) {
    console.error("Discord notify error:", e);
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`abs-stats running on ${PORT}`);
  console.log(`ABS_URL=${ABS_URL}`);
  console.log(`ENGINE_URL=${ENGINE_URL}`);
});
