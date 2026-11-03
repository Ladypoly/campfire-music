"""Shared helpers for the Campfire Radio scripts (pick.py, build.py).

Manifest = months/YYYY-MM.txt, one song per line (edit it freely in the pull request):
    id | title | artist | m:ss | licence | page | audio | cover
- page  = where the song comes from (for the credits), or "own"
- audio = http(s) URL of the original file, or a repo path (tracks/<id>.ogg|mp3|wav for your own songs)
- cover = http(s) URL, repo path, or empty (a cover is drawn)
Lines starting with # are comments; '# title: ...' names the month's mix.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "CampfireRadio/1.0 (+https://github.com/Ladypoly/campfire-music; Banter world jukebox)"
FIELDS = ["id", "title", "artist", "length", "licence", "page", "audio", "cover"]


def path(*parts):
    return os.path.join(ROOT, *parts)


def load_json(rel):
    with open(path(rel), encoding="utf-8") as f:
        return json.load(f)


def slug(text, maxlen=40):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen].rstrip("-")) or "song"


def clean(text):
    """One line, no pipes, no HTML."""
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    text = text.replace("|", "/").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def mmss(seconds):
    seconds = int(round(float(seconds or 0)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def seconds(text):
    try:
        parts = [int(p) for p in str(text).strip().split(":")]
        return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0]
    except ValueError:
        return 0


def read_manifest(rel):
    songs, title = [], ""
    p = path(rel)
    if not os.path.exists(p):
        return songs, title
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.lower().startswith("# title:"):
                title = line.split(":", 1)[1].strip()
                continue
            if not line or line.startswith("#"):
                continue
            cols = [c.strip() for c in line.split("|")]
            cols += [""] * (len(FIELDS) - len(cols))
            songs.append(dict(zip(FIELDS, cols[: len(FIELDS)])))
    return songs, title


def write_manifest(rel, songs, title, header_lines=()):
    with open(path(rel), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# title: {title}\n")
        for h in header_lines:
            f.write(f"# {h}\n")
        f.write("# " + " | ".join(FIELDS) + "\n")
        for s in songs:
            f.write(" | ".join(clean(s.get(k, "")) for k in FIELDS) + "\n")


class RateLimited(Exception):
    pass


def http_get(url, params=None, as_json=True, timeout=25, tries=2):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            return json.loads(data) if as_json else data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimited(url)           # the caller stops asking this service
            last = e
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # network hiccup -> wait and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


def download(url, dest, timeout=180):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = http_get(url, as_json=False, timeout=timeout)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def own_songs():
    """own.txt: id | title | artist | months (e.g. 12 or 10,11; empty = all year) | licence | added (YYYY-MM-DD)"""
    out = []
    p = path("own.txt")
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            c = [x.strip() for x in line.split("|")] + [""] * 6
            sid = c[0]
            audio = next((f"tracks/{sid}.{ext}" for ext in ("ogg", "mp3", "wav", "flac", "m4a") if os.path.exists(path("tracks", f"{sid}.{ext}"))), "")
            if not audio:
                print(f"! own song '{sid}': no tracks/{sid}.ogg/.mp3/.wav - skipped")
                continue
            cover = next((f"covers/{sid}.{ext}" for ext in ("jpg", "jpeg", "png") if os.path.exists(path("covers", f"{sid}.{ext}"))), "")
            months = [m.strip().zfill(2) for m in c[3].split(",") if m.strip()]
            out.append({"id": sid, "title": c[1] or sid, "artist": c[2] or "Campfire", "months": months,
                        "licence": c[4] or "Own (AI)", "added": c[5], "audio": audio, "cover": cover})
    return out
