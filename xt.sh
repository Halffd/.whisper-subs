#!/bin/bash
function subs() {
local movie idx lang subs=
local -a dests=()
for movie
do
ffprobe -loglevel error -select_streams s -show_entries stream=index:stream_tags=language -of csv=p=0 "$movie" |
{
while IFS=, read idx lang
do
subs+=" ${lang}_$idx"
dests+=(-map "0:$idx" "${movie%.*}.${lang}.$idx.srt")
done
if test -n "$subs"
then
echo "Extracting subtitles from $movie:$subs"
ffmpeg -nostdin -y -hide_banner -loglevel quiet -i "$movie" "${dests[@]}"
else
echo "No subtitles in $movie"
fi
}
done
}
subs "$1"
