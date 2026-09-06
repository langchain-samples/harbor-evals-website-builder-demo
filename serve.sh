#!/usr/bin/env bash
# Serve a generated site over HTTP and open it.
#
#   ./serve.sh demo-pages/halden-cycles-scored
#   ./serve.sh workspaces/ccd5dbc76edc 8081
#
# Use this rather than double-clicking index.html when you want the page to
# behave like a real static host: relative paths resolve the same way, and a
# form POST is rejected by the server instead of being silently blocked the
# way browsers block it on file:// URLs.
set -euo pipefail

dir=${1:?usage: ./serve.sh <site-dir> [port]}
port=${2:-8080}

[ -d "$dir" ] || { echo "no such directory: $dir" >&2; exit 1; }
[ -f "$dir/index.html" ] || { echo "no index.html in $dir" >&2; exit 1; }

# Walk to the next free port rather than dead-ending. A demo should never
# stop on "port in use" — an earlier serve.sh is usually still running.
tried=$port
while lsof -ti:"$port" >/dev/null 2>&1; do
  port=$((port + 1))
  if [ "$port" -gt $((tried + 20)) ]; then
    echo "no free port between $tried and $port" >&2
    exit 1
  fi
done
[ "$port" != "$tried" ] && echo "port $tried was busy — using $port instead"

python3 -m http.server "$port" --bind 127.0.0.1 --directory "$dir" >/dev/null 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null || true' EXIT

sleep 0.6
url="http://127.0.0.1:$port/index.html"
echo "serving $dir"
echo "  $url"
echo "  ctrl-c to stop"
open "$url" 2>/dev/null || true
wait $pid
