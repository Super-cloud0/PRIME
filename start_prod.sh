#!/bin/sh
set -eu
python -m flask --app server_prod db upgrade
gunicorn --bind 0.0.0.0:8765 --workers 2 --threads 4 --timeout 90 server_prod:app
