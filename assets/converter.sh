#!/usr/bin/env bash
set -uo pipefail

declare -a gifnames=()
mapfile -d '' -t gifnames < <(find . -type f -iname '*.gif' -print0)

failed=0
for gif in "${gifnames[@]}"; do
  out="${gif%.*}.mp4"
  if [[ -e "$out" ]]; then
    echo "skip (exists): $out"
    continue
  fi

  echo "convert: $gif -> $out"
  if ! ffmpeg -nostdin -hide_banner -loglevel error \
      -stream_loop 3 -i "$gif" \
      -f lavfi -i anullsrc=r=44100:cl=stereo \
      -map 0:v:0 -map 1:a:0 \
      -vf "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos" \
      -c:v libx264 -profile:v high -level 4.1 -pix_fmt yuv420p -crf 18 \
      -c:a aac -b:a 128k -shortest \
      -movflags +faststart \
      "$out"
  then
    echo "FAILED: $gif" >&2
    rm -f -- "$out"
    failed=$((failed + 1))
  fi
done

echo "done: ${#gifnames[@]} found, $failed failed"
exit $(( failed > 0 ))