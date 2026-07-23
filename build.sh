#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt

# Collect static files for WhiteNoise (the project uses ManifestStaticFiles-
# Storage, so this step is REQUIRED or every {% static %} lookup will fail).
python manage.py collectstatic --no-input

python manage.py migrate