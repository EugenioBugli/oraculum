#!/bin/bash
# Download a big file with parallel HTTP range requests (one S3 connection gave ~0.6 MB/s on the lab line).
#   fetch_ranges.sh <url> <out> <size> [parts=16]
set -euo pipefail
url=$1 out=$2 size=$3 n=${4:-16}
part=$(( (size + n - 1) / n ))
seq 0 $((n - 1)) | xargs -P "$n" -I{} bash -c '
    s=$(( {} * '"$part"' )); e=$(( s + '"$part"' - 1 )); [ $e -ge '"$size"' ] && e=$(( '"$size"' - 1 ))
    f='"$out"'.part{}; have=$(stat -c %s "$f" 2>/dev/null || echo 0)
    [ $have -ge $(( e - s + 1 )) ] || curl -fsS --retry 5 -r $(( s + have ))-$e "'"$url"'" >> "$f"'
cat $(seq -f "$out.part%g" 0 $((n - 1))) > "$out"
[ "$(stat -c %s "$out")" = "$size" ] && rm -f "$out".part* && echo "ok: $out ($size bytes)"
