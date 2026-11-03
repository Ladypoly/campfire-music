# campfire-music

Songs, covers, the playlist and the banner slides for the **Campfire** world in Banter.
The world loads everything from here at runtime (GitHub Pages), so adding a song needs **no world rebuild**.

Base URL (after enabling Pages): `https://ladypoly.github.io/campfire-music/`

## Monthly radio (automatic)

Every month the jukebox gets a new playlist: **25 CC0 / public-domain songs found on the web + 5 of your own songs**,
matching the season (December: Christmas songs, October: spooky, ... - see `seasons.json`).

1. **On the 20th** the action *Monthly playlist* searches Wikimedia Commons, Openverse and the Internet Archive
   (only the curated netlabels / Musopen collections) and opens a **pull request** with next month's list
   (`months/YYYY-MM.txt` + an overview with listen links).
2. **You review it**: listen, delete lines you don't like, reorder, add songs. Found something yourself? Put it in
   `picks/YYYY-MM.txt` (see `picks/README.md`) and run the action again for that month (Actions -> Monthly playlist -> Run workflow).
3. **Merge** the pull request. On the **1st** the action *Publish site* downloads everything, matches the loudness,
   converts to Ogg, makes the covers and publishes `playlist.txt` + `CREDITS.md`. No world rebuild.

Nothing is merged without you: automatically found songs can be odd, and no source can promise "made by humans".

### One-time setup (repo settings)

- **Settings -> Pages -> Source: GitHub Actions** (the site is now built by the action, not served from the branch)
- **Settings -> Actions -> General -> Workflow permissions:** "Read and write" + tick **"Allow GitHub Actions to create and approve pull requests"**

## Structure

| Path | What |
|---|---|
| `own.txt` | Your own songs (id, title, artist, months, licence) - 5 go into every month |
| `tracks/`, `covers/` | Audio + cover of your own songs (`tracks/<id>.ogg` or `.mp3`/`.wav`, `covers/<id>.jpg`) |
| `months/YYYY-MM.txt` | The playlist of a month (made by the action, edited by you) |
| `picks/YYYY-MM.txt` | Your hand-picked songs for a month (optional) |
| `seasons.json` | Search words + theme share per month, number of songs, filters |
| `scripts/` | `pick.py` (find songs), `build.py` (build the site) |
| `slides.json`, `slides/` | Tips / featured worlds for the banner |
| *(built)* `playlist.txt`, `CREDITS.md` | Made by `build.py` on the site - what the world reads |

## Add one of your own songs

**Easiest (Windows):** put the files into `import/` (sub folder `12/` = December, `10,11/` = Oct + Nov), double-click `import-songs.bat`. It moves them to `tracks/` + `covers/`, adds the lines to `own.txt` and can push to GitHub. File name = title or "Artist - Title"; a picture with the same name = cover. See `import/LIESMICH.txt`.

By hand:

1. `tracks/<id>.mp3` (or .ogg / .wav) and `covers/<id>.jpg` - id lower case, no spaces
2. A line in `own.txt`: `my-song | My Song | vince_crusty | 12 | Own (Suno)` (`12` = prefer it in December; empty = all year)
3. Commit - it goes into the next playlists (loudness + format are handled by the build)

### File specs (Quest friendly)

- **Audio:** Ogg Vorbis ~128 kbps (or MP3 128–160 kbps), 44.1 kHz stereo, peak-normalised to about −1 dB, ideally loudness-matched (≈ −14 LUFS) so the volume doesn't jump between songs. ~4 MB per 4-minute song. Single files must stay under 100 MB (GitHub limit).
- **Cover:** JPG, 512 × 512, under ~150 KB.
- **Slide image:** JPG, 1024 × 512 (2:1, the banner shape), under ~250 KB.

### Licences

Only add music you may share publicly: your own, or Creative Commons / royalty-free tracks whose licence allows streaming in a public space.
`CC BY` / `CC BY-SA` are easiest (credit is shown on the banner). Avoid `ND`/`NC` unless you have checked it fits.
**No** remixes / edits of commercial songs.

## playlist.txt format (built)

```
# comment lines start with #
id | title | artist | length (m:ss) | licence
when-the-world-ends | When the World Ends | vince_crusty | 3:32 | Own (Suno)
```

- `id` = file name without extension: `tracks/<id>.ogg`, `covers/<id>.jpg`
- `length` keeps everyone in sync before the file has loaded (exact to the second is enough)
- The order of the lines is the play order; the playlist loops.
- Plain text on purpose: the world's visual scripting can't read JSON. (`playlist.json` is no longer used.)
- The jukebox offers the next two songs of this list to vote on.

## Limits (GitHub Pages)

Site ≤ 1 GB (≈ 200 songs), soft limit 100 GB traffic / month (≈ 25 000 song plays).
If we outgrow it, the files move to another host (e.g. Cloudflare R2) and only `baseUrl` changes.
