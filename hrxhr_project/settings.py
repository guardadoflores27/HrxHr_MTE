# hrxhr_project/settings.py
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Secrets & environment ─────────────────────────────────────────────────────
# Everything sensitive comes from environment variables. The fallbacks keep a
# fresh clone runnable locally, but production MUST set real values.
#
# IMPORTANT: this must go through decouple.config(), not plain os.environ.get().
# os.environ.get() only sees REAL OS environment variables — it does NOT read
# a .env file by itself. decouple.config() does: it checks the real
# environment first, then falls back to a .env file next to manage.py. Using
# os.environ.get() here silently ignored .env entirely (DEBUG always fell
# back to its default, no matter what .env said) until this fix.
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-local-development-only-do-not-use-in-production",
)

# DEBUG defaults to False: a missing env var must never expose stack traces.
DEBUG = config("DEBUG", default=False, cast=bool)

# Render injects RENDER_EXTERNAL_HOSTNAME with the public host of the service.
ALLOWED_HOSTS = [h for h in config("ALLOWED_HOSTS", default="").split(",") if h]
RENDER_HOST = config("RENDER_EXTERNAL_HOSTNAME", default=None)
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
# Local development (no RENDER_EXTERNAL_HOSTNAME): allow the usual hosts so a
# fresh clone runs with `python manage.py runserver` and no env setup at all.
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Django 4+ requires the scheme here for POSTs from the deployed domain.
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in
                        ("localhost", "127.0.0.1")]

# ── Security hardening (production only) ────────────────────────────────────
# Everything here is gated by `not DEBUG and RENDER_HOST` on purpose — not
# just `not DEBUG`. Requiring RENDER_HOST too means these can ONLY activate
# when actually running on Render, never from a local `.env` that has DEBUG
# set to False by mistake. This matters most for SECURE_HSTS_SECONDS: once a
# browser receives that header for "localhost", it force-upgrades every
# future request to HTTPS for the next N seconds — which the local dev
# server can't serve — and it won't undo itself just by flipping DEBUG back.
if not DEBUG and RENDER_HOST:
    # Render (like most PaaS) terminates TLS at its own proxy and forwards
    # plain HTTP internally. Without this line, Django can't tell a request
    # arrived over HTTPS, SECURE_SSL_REDIRECT below sees "insecure" on every
    # request (including ones that were already HTTPS) and creates an
    # infinite redirect loop — this line is what prevents that.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    SECURE_SSL_REDIRECT   = True   # http:// requests get redirected to https://
    SESSION_COOKIE_SECURE = True   # session cookie only sent over HTTPS
    CSRF_COOKIE_SECURE    = True   # CSRF cookie only sent over HTTPS

    # HSTS tells the BROWSER to refuse plain HTTP for this host for N seconds
    # — including on its own, before even asking the server. That's powerful
    # but risky to misconfigure: if HTTPS ever breaks, visitors are locked
    # out for the full duration with no quick fix. Start low (1 hour) and
    # only raise this (toward the standard 31536000 = 1 year, then consider
    # SECURE_HSTS_INCLUDE_SUBDOMAINS/SECURE_HSTS_PRELOAD) once HTTPS has been
    # confirmed stable on Render for a few days.
    SECURE_HSTS_SECONDS = 3600

    # Matches Django's own default (True since 3.0) — kept explicit here so
    # this block reads as a complete, deliberate checklist rather than a
    # partial one. Two related headers are already safe out of the box and
    # don't need to be repeated: X_FRAME_OPTIONS (XFrameOptionsMiddleware is
    # installed above, default "DENY") and SECURE_REFERRER_POLICY (default
    # "same-origin" since Django 3.1).
    SECURE_CONTENT_TYPE_NOSNIFF = True

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
# When DATABASE_URL points to Postgres, it takes over from the SQLite default
# above. ssl_require is only forced for Postgres URLs — Postgres (Render's
# managed DB in particular) expects SSL, but forcing it unconditionally broke
# any local DATABASE_URL that isn't Postgres (e.g. sqlite://): the sqlite3
# driver doesn't accept an `sslmode` argument at all and crashes on connect.
DATABASE_URL = config("DATABASE_URL", default=None)
if DATABASE_URL:
    import dj_database_url
    is_postgres = DATABASE_URL.startswith(("postgres://", "postgresql://"))
    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL, conn_max_age=600, ssl_require=is_postgres)

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