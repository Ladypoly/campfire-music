"""Campfire Radio - pick next month's playlist.

    python scripts/pick.py --month 2026-12

Looks for CC0 / public-domain / CC BY MUSIC (no sound effects, talks, podcasts) in
  - Kevin MacLeod / incompetech (CC BY 4.0, professionally produced, preferred)
  - Wikimedia Commons  (lots of public-domain recordings, e.g. US Army / Marine Band carols)
  - Openverse          (Creative Commons search engine: Jamendo, ccMixter, Freesound, Wikimedia ...; licence cc0 / pdm)
  - Internet Archive   (only the curated 'netlabels' and 'musopen' collections - open uploads are often mislabelled)
plus your own hand picks in picks/YYYY-MM.txt (same line format as the manifest, they always go in first).
The month's theme comes from seasons.json (e.g. December: christmas, carol, jingle bells ...).
Your own songs are NOT picked here: build.py adds them every time it publishes (so songs you add during the month
go straight into the running playlist).

Writes months/YYYY-MM.txt (the playlist manifest, edit it in the pull request) and months/YYYY-MM.md (overview).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import threading
import glob
import hashlib
import math
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)   # live log lines in GitHub Actions

LIC_OK = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY"}   # CC BY: the artist is credited on the banner + CREDITS.md
INCOMPETECH = {"list": None, "lock": threading.Lock()}
# Wikimedia Commons is full of field recordings and speeches: a file only counts when its categories say "music"
MUSIC_CATS = re.compile(r"music|song|band|orchestra|choir|chorus|carol|hymn|piano|guitar|violin|jazz|folk|blues|march|waltz|"
                        r"polka|symphon|concerto|sonata|quartet|ensemble|singer|vocal|instrumental|ragtime|lullab", re.I)


def nice_title(t):
    """'09-that_new_traffic_light' -> 'That new traffic light'"""
    t = re.sub(r"\.(mp3|ogg|wav|flac)$", "", t or "", flags=re.I)
    t = re.sub(r"^[\s\d._-]+(?=[^\d])", "", t).replace("_", " ").strip(" -.")
    return (t[:1].upper() + t[1:]) if t else ""


def clean_names(c):
    """'"The Entertainer" (1902), by Scott Joplin' -> title The Entertainer, artist Scott Joplin;
    'Loyalty Freak Music - 08 - Beach' -> Beach; long '(performer)' tails dropped"""
    t = nice_title(c["title"])
    m = re.match(r'^(.+?)\s*(\(\d{4}\))?,?\s+by\s+(.+)$', t)
    if m and (not c["artist"] or c["artist"].lower() in ("unknown", "")):
        t, c["artist"] = m.group(1), m.group(3).strip()
    a = (c["artist"] or "").strip()
    if a and a.lower() != "unknown" and t.lower().startswith(a.lower()):
        t = t[len(a):].lstrip(" -_.:")
    t = re.sub(r"^\d+\s*[-.]\s*", "", t)                                # leading track number
    t = t.strip(" \"'\u201c\u201d")
    if len(t) > 34:
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)                          # '(Olga Gurevich)' etc.
    if len(t) > 34 and " - " in t:                                       # 'Chopin - Waltz ...' / 'Danny Boy - Celtic Aire - ...'
        parts = t.split(" - ")
        t = " - ".join(parts[1:2]) if " " not in parts[0] else parts[0]
    c["title"] = t.strip()


def looks_like_code(t):
    """file-name junk such as '01TPSG7132019Wintera1' or 'hr067 duo de saxos 03'"""
    return (bool(re.search(r"\d{4,}", t)) or (" " not in t and bool(re.search(r"\d", t))) or len(t) < 3
            or bool(re.search(r"\b[a-zA-Z]{1,4}\d+[a-zA-Z0-9]*\b", t)))
OPENVERSE = {"off": False, "lock": threading.Lock()}   # anonymous Openverse: one request at a time, stop on 429


# ---------------------------------------------------------------- sources
def from_openverse(term, seasonal):
    out = []
    for page in (1,):
        if OPENVERSE["off"]:
            break
        try:
            with OPENVERSE["lock"]:
                r = C.http_get("https://api.openverse.org/v1/audio/", {
                    "q": term, "license": "cc0,pdm,by", "category": "music", "page_size": 20, "page": page, "mature": "false"})
                time.sleep(1.0)
        except C.RateLimited:
            print("  openverse: rate limit reached - no more Openverse searches this run")
            OPENVERSE["off"] = True
            break
        except Exception as e:
            print(f"  openverse '{term}': {e}")
            break
        for x in r.get("results", []):
            lic = (x.get("license") or "").lower()
            if lic not in LIC_OK or not x.get("url"):
                continue
            lv = x.get("license_version") or ""
            out.append({"title": x.get("title") or "", "artist": x.get("creator") or "unknown",
                        "secs": (x.get("duration") or 0) / 1000.0, "licence": LIC_OK[lic] + (f" {lv}" if lic == "by" and lv else ""),
                        "page": x.get("foreign_landing_url") or "", "audio": x["url"], "cover": x.get("thumbnail") or "",
                        "tags": " ".join(t.get("name", "") for t in (x.get("tags") or [])),
                        "source": "openverse/" + (x.get("source") or "?"), "seasonal": seasonal, "pop": 0})
    return out


def from_commons(term, seasonal):
    out = []
    try:
        r = C.http_get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{term} filetype:audio", "gsrlimit": 40, "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName|ImageDescription|Categories"})
    except Exception as e:
        print(f"  commons '{term}': {e}")
        return out
    for p in (r.get("query", {}).get("pages", {}) or {}).values():
        info = (p.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if not mime.startswith(("audio/", "application/ogg", "video/webm")) or "midi" in mime:
            continue
        meta = info.get("extmetadata", {})
        lic = C.clean(meta.get("LicenseShortName", {}).get("value", "")).lower()
        if lic in ("cc0", "cc0 1.0", "cc-zero"):
            licence = "CC0"
        elif lic.startswith("public domain") or lic in ("pd", "pdm"):
            licence = "Public Domain"
        elif re.match(r"^cc[ -]by \d", lic):                          # CC BY x.x (not -SA / -NC / -ND)
            licence = "CC BY " + lic.split()[-1]
        else:
            continue
        cats = C.clean(meta.get("Categories", {}).get("value", ""))
        if not MUSIC_CATS.search(cats):
            continue
        name = re.sub(r"^File:", "", p.get("title", ""))
        title = C.clean(meta.get("ObjectName", {}).get("value", "")) or re.sub(r"\.\w+$", "", name)
        artist = C.clean(meta.get("Artist", {}).get("value", "")) or "unknown"
        out.append({"title": title, "artist": artist[:60], "secs": float(info.get("duration") or 0), "licence": licence,
                    "page": info.get("descriptionurl") or "https://commons.wikimedia.org/wiki/" + p.get("title", "").replace(" ", "_"),
                    "audio": info.get("url", ""), "cover": "",
                    "tags": (cats + " " + C.clean(meta.get("ImageDescription", {}).get("value", "")))[:400],
                    "source": "wikimedia", "seasonal": seasonal, "pop": 0})
    return out


def from_archive(term, seasonal, rng):
    out = []
    q = (f'collection:(netlabels OR musopen) AND mediatype:audio AND (licenseurl:(*publicdomain*) OR licenseurl:(*licenses/by/*)) '
         f'AND (subject:("{term}") OR title:("{term}"))')
    try:
        r = C.http_get("https://archive.org/advancedsearch.php", {
            "q": q, "fl[]": ["identifier", "title", "creator", "downloads", "licenseurl", "subject"],
            "sort[]": "downloads desc", "rows": 8, "output": "json"})
    except Exception as e:
        print(f"  archive '{term}': {e}")
        return out
    docs = r.get("response", {}).get("docs", [])

    def meta_of(doc):
        try:
            return C.http_get(f"https://archive.org/metadata/{doc['identifier']}")
        except Exception as e:
            print(f"  archive item {doc['identifier']}: {e}")
            return None
    with cf.ThreadPoolExecutor(4) as ex:
        metas = list(ex.map(meta_of, docs))
    for doc, meta in zip(docs, metas):
        ident = doc["identifier"]
        lu = str(doc.get("licenseurl", ""))
        licence = "CC0" if "zero" in lu else ("Public Domain" if "publicdomain" in lu else "CC BY " + (re.findall(r"/by/([\d.]+)", lu) or ["4.0"])[0])
        if not meta:
            continue
        files = [f for f in meta.get("files", []) if "MP3" in f.get("format", "") or f.get("format") == "Ogg Vorbis"]
        files = [f for f in files if f.get("format") in ("VBR MP3", "128Kbps MP3", "MP3", "Ogg Vorbis")]
        if not files:
            continue
        f = rng.choice(files)                      # one song per release
        secs = f.get("length") or 0
        secs = C.seconds(secs) if ":" in str(secs) else float(secs or 0)
        creator = doc.get("creator") or f.get("artist") or f.get("creator") or "unknown"
        if isinstance(creator, list):
            creator = ", ".join(creator)
        subj = doc.get("subject") or ""
        if isinstance(subj, list):
            subj = " ".join(subj)
        out.append({"title": f.get("title") or re.sub(r"\.\w+$", "", f["name"]), "artist": creator, "secs": secs,
                    "licence": licence, "page": f"https://archive.org/details/{ident}",
                    "audio": f"https://archive.org/download/{ident}/" + C.urllib.parse.quote(f["name"]),
                    "cover": f"https://archive.org/services/img/{ident}", "tags": f"{doc.get('title', '')} {subj}",
                    "source": "archive.org", "seasonal": seasonal, "pop": int(doc.get("downloads") or 0)})
    return out


def from_incompetech(term, seasonal):
    """Kevin MacLeod's library (incompetech.com, CC BY 4.0): one JSON list, matched on title / description / feel / instruments."""
    with INCOMPETECH["lock"]:
        if INCOMPETECH["list"] is None:
            try:
                INCOMPETECH["list"] = C.http_get("https://incompetech.com/music/royalty-free/pieces.json", timeout=60)
            except Exception as e:
                print(f"  incompetech: {e}")
                INCOMPETECH["list"] = []
    out, t = [], term.lower()
    for x in INCOMPETECH["list"]:
        text = " ".join(str(x.get(k) or "") for k in ("title", "description", "feel", "instruments")).lower()
        if not re.search(r"\b" + re.escape(t) + r"\b", text) or not x.get("filename"):
            continue
        out.append({"title": x.get("title") or "", "artist": "Kevin MacLeod", "secs": C.seconds(str(x.get("length") or "0").split(":", 1)[-1]) if str(x.get("length", "")).count(":") == 2 else C.seconds(x.get("length") or 0),
                    "licence": "CC BY 4.0",
                    "page": "https://incompetech.com/music/royalty-free/index.html?isrc=" + str(x.get("isrc") or ""),
                    "audio": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/" + C.urllib.parse.quote(x["filename"]),
                    "cover": "", "tags": f"{x.get('feel', '')} {x.get('description', '')}",
                    "source": "incompetech", "seasonal": seasonal, "pop": 0})
    return out


# ---------------------------------------------------------------- picking
def used_before(month, n_months):
    """audio URLs + page URLs used in the n months before `month`"""
    used = set()
    y, m = map(int, month.split("-"))
    for k in range(1, n_months + 1):
        mm = (y * 12 + m - 1 - k)
        songs, _ = C.read_manifest(f"months/{mm // 12:04d}-{mm % 12 + 1:02d}.txt")
        for s in songs:
            used.update({s["audio"], s["page"]} - {"", "own"})
    return used


def own_usage():
    count = {}
    for f in glob.glob(C.path("months", "*.txt")):
        for s in C.read_manifest(os.path.relpath(f, C.ROOT))[0]:
            if s["page"] == "own":
                count[s["id"]] = count.get(s["id"], 0) + 1
    return count


def main():
    ap = argparse.ArgumentParser()
    today = dt.date.today()
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    ap.add_argument("--month", default=nxt.strftime("%Y-%m"), help="YYYY-MM (default: next month)")
    ap.add_argument("--sources", default="incompetech,openverse,commons,archive")
    args = ap.parse_args()
    month = args.month
    cfg = C.load_json("seasons.json")
    mcfg = cfg["months"][month[5:7]]
    rng = random.Random(month)                     # same month -> same picks (re-runs are reproducible)
    excl = [w.lower() for w in cfg["exclude_words"]]
    lo, hi = cfg["min_seconds"], cfg["max_seconds"]
    recent = used_before(month, cfg["skip_recent_months"])
    srcs = args.sources.split(",")
    print(f"== {month}: {mcfg['name']} (theme share {mcfg['share']:.0%})")

    def search(t, seasonal):
        found = []
        if "incompetech" in srcs: found += from_incompetech(t, seasonal)
        if "commons" in srcs: found += from_commons(t, seasonal)
        if "openverse" in srcs: found += from_openverse(t, seasonal)
        if "archive" in srcs: found += from_archive(t, seasonal, random.Random(month + t))
        print(f"- '{t}': {len(found)} candidates")
        return found

    def gather(terms, seasonal):          # a few search words in parallel (each source stays polite)
        with cf.ThreadPoolExecutor(4) as ex:
            return [c for part in ex.map(lambda t: search(t, seasonal), terms) for c in part]

    def ok(c):
        clean_names(c)
        if looks_like_code(c["title"]):
            return False
        text = f"{c['title']} {c['artist']} {c['tags']}".lower()
        if any(w in text for w in excl):
            return False
        if c["secs"] and not (lo <= c["secs"] <= hi):
            return False
        return c["audio"] not in recent and c["page"] not in recent

    seasonal = [c for c in gather(mcfg["seasonal"], True) if ok(c)]
    general = [c for c in gather(cfg["general"], False) if ok(c)]
    for c in seasonal + general:   # a bit of luck + trusted sources + popularity; unknown length = slightly lower
        c["score"] = rng.random() + {"incompetech": 0.45, "openverse/jamendo": 0.3, "wikimedia": 0.1, "archive.org": 0.1}.get(c["source"], 0.1) \
            + 0.05 * math.log10(1 + c["pop"]) - (0.2 if not c["secs"] else 0)

    n_total = cfg["found_songs"]
    manual, _ = C.read_manifest(f"picks/{month}.txt")
    picked, seen, per_artist = [], set(), {}

    def take(c):
        key = C.slug(c["title"]) + "/" + C.slug(c["artist"])
        a = C.slug(c["artist"])
        cap = {C.slug(k): v for k, v in cfg.get("artist_caps", {}).items()}.get(a, cfg["max_per_artist"])
        if key in seen or (a != "unknown" and per_artist.get(a, 0) >= cap):
            return False
        seen.add(key); per_artist[a] = per_artist.get(a, 0) + 1
        picked.append(c)
        return True

    for s in manual:
        take({"title": s["title"], "artist": s["artist"], "secs": C.seconds(s["length"]), "licence": s["licence"],
              "page": s["page"], "audio": s["audio"], "cover": s["cover"], "source": "hand pick", "seasonal": False})
    want_seasonal = round(n_total * mcfg["share"])
    for c in sorted(seasonal, key=lambda c: -c["score"]):
        if len(picked) >= len(manual) + want_seasonal: break
        take(c)
    for c in sorted(general, key=lambda c: -c["score"]):
        if len(picked) >= n_total: break
        take(c)
    for c in sorted(seasonal, key=lambda c: -c["score"]):   # not enough general music -> more theme songs
        if len(picked) >= n_total: break
        take(c)
    rng.shuffle(picked)

    songs = []
    for c in picked:
        h = hashlib.sha1(c["audio"].encode()).hexdigest()[:6]
        c["id"] = f"{C.slug(c['title'], 30)}-{h}"
        songs.append({"id": c["id"], "title": c["title"], "artist": c["artist"], "length": C.mmss(c["secs"]) if c["secs"] else "",
                      "licence": c["licence"], "page": c["page"], "audio": c["audio"], "cover": c["cover"]})

    title = f"{mcfg['name']} {dt.date(int(month[:4]), int(month[5:]), 1):%B %Y}"
    os.makedirs(C.path("months"), exist_ok=True)
    C.write_manifest(f"months/{month}.txt", songs, title, [
        f"generated {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC by scripts/pick.py - edit freely: delete a line to drop a song, reorder lines to change the order"])

    # overview for the pull request
    src_of = {c["id"]: c for c in picked}
    lines = [f"## Campfire Radio - {title}", "",
             f"{len(picked)} found songs ({sum(1 for c in picked if c.get('seasonal'))} matching the theme).",
             "Your own songs (own.txt) are mixed in automatically when the site is published - also the ones you add during the month.",
             f"Candidates: {len(seasonal)} theme / {len(general)} general after filtering.", "",
             "Listen through the links, then **delete lines you don't like** in `months/" + month + ".txt` (or add your own to `picks/" + month + ".txt` and re-run).",
             "Merging this pull request publishes the playlist on the 1st of the month.", "",
             "| # | Song | Artist | Licence | Length | Source | Theme |", "|---|---|---|---|---|---|---|"]
    for i, s in enumerate(songs, 1):
        c = src_of.get(s["id"], {})
        src = f"[{c.get('source', 'link')}]({s['page'] or s['audio']})"
        lines.append(f"| {i} | {C.clean(s['title'])} | {C.clean(s['artist'])} | {s['licence']} | {s['length'] or '?'} | {src} | {'yes' if c.get('seasonal') else ''} |")
    if len(picked) < n_total:
        lines += ["", f"**Only {len(picked)} of {n_total} found** - add hand picks in `picks/{month}.txt` or more search words in `seasons.json`."]
    with open(C.path("months", f"{month}.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote months/{month}.txt ({len(songs)} songs)")


if __name__ == "__main__":
    main()
