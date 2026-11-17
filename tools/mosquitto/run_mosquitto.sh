#!/usr/bin/env bash
# Linux only, no sudo: runs the Mosquitto 2.0.18 binary extracted from the
# Ubuntu 24.04 .deb files into tools/mosquitto/root (see docs/MQTT_SETUP.md).
# Usage: tools/mosquitto/run_mosquitto.sh [port] [nodelay true|false]
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-1883}"
NODELAY="${2:-true}"
export LD_LIBRARY_PATH="$HERE/root/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
CONF="$(mktemp)"
printf 'listener %s 127.0.0.1\nallow_anonymous true\nset_tcp_nodelay %s\n' "$PORT" "$NODELAY" > "$CONF"
exec "$HERE/root/usr/sbin/mosquitto" -c "$CONF"
