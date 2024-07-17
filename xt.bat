@echo off
setlocal enabledelayedexpansion

set "subs="
set "dests="

for %%f in (*.mkv) do (
    for /f "tokens=1,2 delims=," %%i in ('C:\Users\halff\OneDrive\Documents\.bat\ffprobe.exe -loglevel error -select_streams s -show_entries stream=index^:stream_tags^=language -of csv^=p^=0 "%%f"') do (
        set "idx=%%i"
        set "lang=%%j"
        set "subs=!subs! !lang!_!idx!"
        set "dests=!dests! -map "0:!idx!" "%%~nf.!lang!.!idx!.srt""
    )

    if not "!subs!"=="" (
        echo Extracting subtitles from %%f:!subs!
        ffmpeg -nostdin -y -hide_banner -loglevel quiet -i "%%f" !dests!
    ) else (
        echo No subtitles in %%f
    )

    set "subs="
    set "dests="
)
pause