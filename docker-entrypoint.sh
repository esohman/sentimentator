#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${SECRET_KEY:?SECRET_KEY must be set}"

mkdir -p /var/sentimentator-data
python init_emomap_db.py
exec "$@"
