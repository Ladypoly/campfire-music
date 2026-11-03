"""Campfire Radio - pick next month's playlist.

    python scripts/pick.py --month 2026-12

Looks for CC0 / public-domain MUSIC (no sound effects, talks, podcasts) in
  - Wikimedia Commons  (lots of public-domain recordings, e.g. US Army / Marine Band carols)
  - Openverse          (Creative Commons search engine: Jamendo, ccMixter, Freesound, Wikimedia ...; licence cc0 / pdm)
  - Internet Archive   (only the curated 'netlabels' and 'musopen' collections - open uploads are often mislabelled)
plus your own hand picks in picks/YYYY-MM.txt (same line format as the manifest, they always go in first).
The month's theme comes from seasons.json (e.g. December: christmas, carol, jingle bells ...).
Then it adds your own songs from own.txt (songs tagged for this month first, then the ones played least).

Writes months/YYYY-MM.txt (the playlist manifest, edit it in the pull request) and months/YYYY-MM.md (overview).
"""
import argparse
import datetime as dt
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

LIC_OK = {"cc0": "CC0", "pdm": "Public Domain"}


# ---------------------------------------------------------------- sources
def from_openverse(term, seasonal):
    out = []
    for page in (1, 2):
        try:
            r = C.http_get("https://api.openverse.org/v1/audio/", {
                "q": term, "license": "cc0,pdm", "category": "music", "page_size": 20, "page": page, "mature": "false"})
        except Exception as e:
            print(f"  openverse '{term}': {e}")
            break
        for x in r.get("results", []):
            lic = (x.get("license") or "").lower()
            if lic not in LIC_OK or not x.get("url"):
                continue
            out.append({"title": x.get("title") or "", "artist": x.get("creator") or "unknown",
                        "secs": (x.get("duration") or 0) / 1000.0, "licence": LIC_OK[lic],
                        "page": x.get("foreign_landing_url") or "", "audio": x["url"], "cover": x.get("thumbnail") or "",
                        "tags": " ".join(t.get("name", "") for t in (x.get("tags") or [])),
                        "source": "openverse/" + (x.get("source") or "?"), "seasonal": seasonal, "pop": 0})
        if r.get("page_count", 1) <= page:
            break
        time.sleep(1.5)          # anonymous API: stay well under the rate limit
    return out


def from_commons(term, seasonal):
    out = []
    try:
        r = C.http_get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{term} filetype:audio", "gsrlimit": 40, "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName|ImageDescription"})
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
        else:
            continue
        name = re.sub(r"^File:", "", p.get("title", ""))
        title = C.clean(meta.get("ObjectName", {}).get("value", "")) or re.sub(r"\.\w+$", "", name)
        artist = C.clean(meta.get("Artist", {}).get("value", "")) or "unknown"
        out.append({"title": title, "artist": artist[:60], "secs": float(info.get("duration") or 0), "licence": licence,
                    "page": info.get("descriptionurl") or "https://commons.wikimedia.org/wiki/" + p.get("title", "").replace(" ", "_"),
                    "audio": info.get("url", ""), "cover": "",
                    "tags": C.clean(meta.get("ImageDescription", {}).get("value", ""))[:300],
                    "source": "wikimedia", "seasonal": seasonal, "pop": 0})
    return out


def from_archive(term, seasonal, rng):
    out = []
    q = (f'collection:(netlabels OR musopen) AND mediatype:audio AND licenseurl:(*publicdomain*) '
         f'AND (subject:("{term}") OR title:("{term}"))')
    try:
        r = C.http_get("https://archive.org/advancedsearch.php", {
            "q": q, "fl[]": ["identifier", "title", "creator", "downloads", "licenseurl"],
            "sort[]": "downloads desc", "rows": 15, "output": "json"})
    except Exception as e:
        print(f"  archive '{term}': {e}")
        return out
    for doc in r.get("response", {}).get("docs", []):
        ident = doc["identifier"]
        licence = "CC0" if "zero" in str(doc.get("licenseurl", "")) else "Public Domain"
        try:
            meta = C.http_get(f"https://archive.org/metadata/{ident}")
        except Exception as e:
            print(f"  archive item {ident}: {e}")
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
        out.append({"title": f.get("title") or re.sub(r"\.\w+$", "", f["name"]), "artist": creator, "secs": secs,
                    "licence": licence, "page": f"https://archive.org/details/{ident}",
                    "audio": f"https://archive.org/download/{ident}/" + C.urllib.parse.quote(f["name"]),
                    "cover": f"https://archive.org/services/img/{ident}", "tags": doc.get("title", ""),
                    "source": "archive.org", "seasonal": seasonal, "pop": int(doc.get("downloads") or 0)})
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
    ap.add_argument("--sources", default="commons,openverse,archive")
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

    def gather(terms, seasonal):
        found = []
        for t in terms:
            print(f"- searching '{t}'")
            if "commons" in srcs: found += from_commons(t, seasonal)
            if "openverse" in srcs: found += from_openverse(t, seasonal)
            if "archive" in srcs: found += from_archive(t, seasonal, rng)
        return found

    def ok(c):
        text = f"{c['title']} {c['tags']}".lower()
        if any(w in text for w in excl):
            return False
        if c["secs"] and not (lo <= c["secs"] <= hi):
            return False
        return c["audio"] not in recent and c["page"] not in recent

    seasonal = [c for c in gather(mcfg["seasonal"], True) if ok(c)]
    general = [c for c in gather(cfg["general"], False) if ok(c)]
    for c in seasonal + general:   # a bit of luck + trusted sources + popularity; unknown length = slightly lower
        c["score"] = rng.random() + {"wikimedia": 0.15, "archive.org": 0.2}.get(c["source"], 0.1) \
            + 0.05 * math.log10(1 + c["pop"]) - (0.2 if not c["secs"] else 0)

    n_total = cfg["found_songs"]
    manual, _ = C.read_manifest(f"picks/{month}.txt")
    picked, seen, per_artist = [], set(), {}

    def take(c):
        key = C.slug(c["title"]) + "/" + C.slug(c["artist"])
        a = C.slug(c["artist"])
        if key in seen or (a != "unknown" and per_artist.get(a, 0) >= cfg["max_per_artist"]):
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

    # own songs: tagged for this month first, then the ones played least
    usage = own_usage()
    own = C.own_songs()
    own.sort(key=lambda o: (0 if month[5:7] in o["months"] else (2 if o["months"] else 1), usage.get(o["id"], 0), rng.random()))
    own = own[: cfg["own_songs"]]

    songs = []
    for c in picked:
        h = hashlib.sha1(c["audio"].encode()).hexdigest()[:6]
        c["id"] = f"{C.slug(c['title'], 30)}-{h}"
        songs.append({"id": c["id"], "title": c["title"], "artist": c["artist"], "length": C.mmss(c["secs"]) if c["secs"] else "",
                      "licence": c["licence"], "page": c["page"], "audio": c["audio"], "cover": c["cover"]})
    # spread the own songs evenly through the mix
    for i, o in enumerate(own):
        pos = round((i + 0.5) * (len(songs) + len(own)) / max(1, len(own)))
        songs.insert(min(pos, len(songs)), {"id": o["id"], "title": o["title"], "artist": o["artist"], "length": "",
                                            "licence": o["licence"], "page": "own", "audio": o["audio"], "cover": o["cover"]})

    title = f"{mcfg['name']} {dt.date(int(month[:4]), int(month[5:]), 1):%B %Y}"
    os.makedirs(C.path("months"), exist_ok=True)
    C.write_manifest(f"months/{month}.txt", songs, title, [
        f"generated {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC by scripts/pick.py - edit freely: delete a line to drop a song, reorder lines to change the order"])

    # overview for the pull request
    src_of = {c["id"]: c for c in picked}
    lines = [f"## Campfire Radio - {title}", "",
             f"{len(picked)} found songs ({sum(1 for c in picked if c.get('seasonal'))} matching the theme) + {len(own)} own songs.",
             f"Candidates: {len(seasonal)} theme / {len(general)} general after filtering.", "",
             "Listen through the links, then **delete lines you don't like** in `months/" + month + ".txt` (or add your own to `picks/" + month + ".txt` and re-run).",
             "Merging this pull request publishes the playlist on the 1st of the month.", "",
             "| # | Song | Artist | Licence | Length | Source | Theme |", "|---|---|---|---|---|---|---|"]
    for i, s in enumerate(songs, 1):
        c = src_of.get(s["id"], {})
        src = "own" if s["page"] == "own" else f"[{c.get('source', 'link')}]({s['page'] or s['audio']})"
        lines.append(f"| {i} | {C.clean(s['title'])} | {C.clean(s['artist'])} | {s['licence']} | {s['length'] or '?'} | {src} | {'yes' if c.get('seasonal') else ''} |")
    if len(picked) < n_total:
        lines += ["", f"**Only {len(picked)} of {n_total} found** - add hand picks in `picks/{month}.txt` or more search words in `seasons.json`."]
    with open(C.path("months", f"{month}.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote months/{month}.txt ({len(songs)} songs)")


if __name__ == "__main__":
    main()
