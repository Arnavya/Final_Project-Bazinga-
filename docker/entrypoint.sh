#!/bin/sh
# Seed the writable state directory from the image's read-only seed, then start the app.
# Existing files are never overwritten, so learned lessons on a persistent volume survive
# restarts and upgrades.
set -eu

STORES_DIR="${STORES_DIR:-/app/stores}"
SEED_DIR="/app/stores-seed"

mkdir -p "$STORES_DIR"
for src in "$SEED_DIR"/*; do
  [ -e "$src" ] || continue
  dest="$STORES_DIR/$(basename "$src")"
  if [ ! -e "$dest" ]; then
    cp "$src" "$dest"
  fi
done

exec "$@"
