# hrxhr_project/settings.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Secrets & environment ─────────────────────────────────────────────────────
# Everything sensitive comes from environment variables. The fallbacks keep a
# fresh clone runnable locally, but production MUST set real values.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-local-development-only-do-not-use-in-production",
)

# DEBUG defaults to False: a missing env var must never expose stack traces.
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")

# Render injects RENDER_EXTERNAL_HOSTNAME with the public host of the service.
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
# Local development (no RENDER_EXTERNAL_HOSTNAME): allow the usual hosts so a
# fresh clone runs with `python manage.py runserver` and no env setup at all.
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Django 4+ requires the scheme here for POSTs from the deployed domain.
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in
                        ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # project apps
    'core',
    'planning',
    'production',
    'resources',
    'analytics',
    'users',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # ← after SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hrxhr_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],          # ← global templates folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hrxhr_project.wsgi.application'

# ── Database (SQLite for dev, swap DATABASE_URL for Postgres in prod) ──────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# On Render the filesystem is ephemeral — SQLite would be wiped on every deploy.
# When DATABASE_URL is present (a Render Postgres instance) it takes over.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url
    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL, conn_max_age=600, ssl_require=True)

# ── Static files ───────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # collectstatic target
STATICFILES_DIRS = [BASE_DIR / 'static']   # project-level static assets

STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# ── Auth ───────────────────────────────────────────────────────────────────────
LOGIN_URL          = '/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/users/login/'

# ── i18n ───────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'America/Tijuana'
USE_I18N = True
USE_TZ   = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'