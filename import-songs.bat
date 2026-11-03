@echo off
rem Campfire Radio - import your own songs from the "import" folder (see import-songs.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0import-songs.ps1"
