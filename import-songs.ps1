# Campfire Radio - import your own songs.
# Put audio files (mp3 / wav / ogg / flac / m4a) into the "import" folder and double-click import-songs.bat.
#  - File name = song title, or "Artist - Title" (e.g. "vince_crusty - Snowy Campfire.mp3")
#  - Cover (optional): an image with the same name next to it (Snowy Campfire.jpg / .png)
#  - Month: put the files into a sub folder named after the month(s): import\12\  or  import\10,11\  (no folder = all year)
#  - Default artist / licence: import\settings.txt  (artist=... / licence=...)
# The files are moved to tracks\ and covers\ and a line is added to own.txt. Then it can upload everything to GitHub.
$ErrorActionPreference = 'Stop'
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$import = Join-Path $root 'import'
$tracks = Join-Path $root 'tracks'
$covers = Join-Path $root 'covers'
$own    = Join-Path $root 'own.txt'
$utf8   = New-Object System.Text.UTF8Encoding($false)
foreach ($d in @($import, $tracks, $covers)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null } }

# defaults
$artist = 'vince_crusty'; $licence = 'Own (Suno)'
$settings = Join-Path $import 'settings.txt'
if (Test-Path $settings) {
    foreach ($l in [IO.File]::ReadAllLines($settings, $utf8)) {
        if ($l -match '^\s*artist\s*=\s*(.+)$')  { $artist  = $Matches[1].Trim() }
        if ($l -match '^\s*licence\s*=\s*(.+)$') { $licence = $Matches[1].Trim() }
    }
} else {
    [IO.File]::WriteAllText($settings, "artist=$artist`r`nlicence=$licence`r`n", $utf8)
}

function Get-Slug([string]$text) {
    $n = $text.Normalize([Text.NormalizationForm]::FormD)
    $sb = New-Object System.Text.StringBuilder
    foreach ($c in $n.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($c) -ne [Globalization.UnicodeCategory]::NonSpacingMark) { [void]$sb.Append($c) }
    }
    $s = ($sb.ToString().ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
    if ($s.Length -gt 40) { $s = $s.Substring(0, 40).TrimEnd('-') }
    if (-not $s) { $s = 'song' }
    return $s
}
function Clean([string]$t) { return (($t -replace '\|', '/') -replace '\s+', ' ').Trim() }

# ids already in use
$ownText = ''
if (Test-Path $own) { $ownText = [IO.File]::ReadAllText($own, $utf8) }
$used = @{}
foreach ($l in ($ownText -split "`n")) { $l = $l.Trim(); if ($l -and -not $l.StartsWith('#')) { $used[($l.Split('|')[0]).Trim()] = $true } }
foreach ($f in Get-ChildItem $tracks -File) { $used[$f.BaseName] = $true }

$audioExt = @('.mp3', '.wav', '.ogg', '.flac', '.m4a')
$files = @(Get-ChildItem $import -Recurse -File | Where-Object { $audioExt -contains $_.Extension.ToLowerInvariant() } | Sort-Object FullName)
if ($files.Count -eq 0) {
    Write-Host "Keine Songs im Ordner import gefunden." -ForegroundColor Yellow
    Write-Host "Lege mp3/wav/ogg-Dateien in $import (Unterordner 12 = Dezember usw.) und starte das Skript noch mal."
    Read-Host "Enter zum Beenden"; exit
}

$lines = @(); $count = 0
foreach ($f in $files) {
    # month from the sub folder name (12  or  10,11)
    $months = ''
    $rel = $f.DirectoryName.Substring($import.Length).Trim('\', '/')
    if ($rel) {
        $leaf = Split-Path $rel -Leaf
        if ($leaf -match '^\d{1,2}(,\s*\d{1,2})*$') { $months = (($leaf -split ',') | ForEach-Object { '{0:D2}' -f [int]$_.Trim() }) -join ',' }
    }
    # "Artist - Title" or just "Title"; copy suffixes like "_1" or " (2)" are dropped
    $name = $f.BaseName -replace '(_\d+| \(\d+\))$', ''
    $a = $artist; $title = $name
    if ($name -match '^(.+?)\s+-\s+(.+)$') { $a = $Matches[1].Trim(); $title = $Matches[2].Trim() }
    $title = Clean $title; $a = Clean $a
    if ($f.Length -gt 95MB) { Write-Host "  ! $($f.Name) ist groesser als 95 MB (GitHub-Limit 100 MB) - bitte als mp3 exportieren. Uebersprungen." -ForegroundColor Red; continue }

    $id = Get-Slug $title; $base = $id; $k = 2
    while ($used.ContainsKey($id)) { $id = "$base-$k"; $k++ }
    $used[$id] = $true

    Move-Item -LiteralPath $f.FullName -Destination (Join-Path $tracks ($id + $f.Extension.ToLowerInvariant()))
    $coverNote = 'Cover wird gezeichnet'
    foreach ($ext in @('.jpg', '.jpeg', '.png')) {
        $c = Join-Path $f.DirectoryName ($f.BaseName + $ext)
        if (Test-Path -LiteralPath $c) { Move-Item -LiteralPath $c -Destination (Join-Path $covers ($id + $ext)); $coverNote = "Cover $ext"; break }
    }
    $lines += "$id | $title | $a | $months | $licence | $(Get-Date -Format 'yyyy-MM-dd')"
    $count++
    $when = 'ganzjaehrig'; if ($months) { $when = "Monat $months" }
    Write-Host ("  + {0,-34} {1}  ({2}, {3})" -f $id, $title, $when, $coverNote) -ForegroundColor Green
}

if ($count -gt 0) {
    $prefix = ''
    if ($ownText -and -not $ownText.EndsWith("`n")) { $prefix = "`r`n" }
    [IO.File]::AppendAllText($own, $prefix + (($lines -join "`r`n") + "`r`n"), $utf8)
    Write-Host ""
    Write-Host "$count Song(s) importiert und in own.txt eingetragen." -ForegroundColor Cyan
    # remove empty month folders
    Get-ChildItem $import -Recurse -Directory | Sort-Object FullName -Descending | Where-Object { -not (Get-ChildItem $_.FullName -Force) } | Remove-Item

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $answer = Read-Host "Jetzt zu GitHub hochladen? (j/n)"
        if ($answer -match '^[jJyY]') {
            Push-Location $root
            try {
                git add -- tracks covers own.txt
                git commit -m "Add $count own song(s)"
                git push
                Write-Host "Hochgeladen. Die Songs kommen in die naechste Monats-Playlist." -ForegroundColor Cyan
            } finally { Pop-Location }
        }
    } else {
        Write-Host "git nicht gefunden - bitte tracks, covers und own.txt selbst committen und pushen."
    }
}
Read-Host "Enter zum Beenden"
