"""Django settings for the Equipment Damage Tracker.

Everything that differs between a developer laptop and the Windows PC is read
from environment variables (see .env.example and deploy/windows/README.md).
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Read KEY=value lines from faults.env (if present) into the environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env_file(BASE_DIR / "faults.env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# All data (database, photos, secret key) lives in one folder so the program can
# be moved to another machine by copying it (architecture 7.6).
DATA_DIR = Path(os.environ.get("FAULTS_DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_secret_key():
    if os.environ.get("FAULTS_SECRET_KEY"):
        return os.environ["FAULTS_SECRET_KEY"]
    key_file = DATA_DIR / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


SECRET_KEY = _load_secret_key()

DEBUG = env_bool("FAULTS_DEBUG", False)

ALLOWED_HOSTS = env_list("FAULTS_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("FAULTS_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "faults.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.permissions",
            ],
        },
    },
]

WSGI_APPLICATION = "faults.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            # WAL lets readers carry on while someone saves; IMMEDIATE avoids
            # "database is locked" errors when two people save at once.
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

# No password rules: Leon chose simple passwords over high security (2026-11-18).
# Any non-blank password is accepted.
AUTH_PASSWORD_VALIDATORS = []

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Lock an account for a while after repeated failed logins (architecture 9).
LOGIN_MAX_FAILURES = int(os.environ.get("FAULTS_LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("FAULTS_LOGIN_LOCKOUT_MINUTES", "15"))

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Photos are stored here and only served through a login-protected view.
PHOTOS_DIR = DATA_DIR / "photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_MAX_UPLOAD_BYTES = int(os.environ.get("FAULTS_PHOTO_MAX_MB", "20")) * 1024 * 1024
PHOTO_MAX_EDGE = 2000
PHOTO_THUMB_EDGE = 320
DATA_UPLOAD_MAX_NUMBER_FILES = 30

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# HTTPS (architecture 7.5). Caddy terminates TLS and forwards to Waitress on
# 127.0.0.1, setting X-Forwarded-Proto. Set FAULTS_HTTPS=0 only for local dev.
if env_bool("FAULTS_HTTPS", not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_AGE = 60 * 60 * 12  # one working day

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
