"""Configuração do servidor Apura BU (apuracao.tonicoimbra.com)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_lista(nome, padrao=''):
    return [x.strip() for x in os.environ.get(nome, padrao).split(',') if x.strip()]


SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-inseguro-troque-em-producao')
DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
ALLOWED_HOSTS = env_lista('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,apuracao.tonicoimbra.com')
CSRF_TRUSTED_ORIGINS = env_lista('DJANGO_CSRF_ORIGINS', 'https://apuracao.tonicoimbra.com')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'boletins',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Sem nginx na VPS (portas 80/443 são do Traefik do Easypanel): o próprio Django serve /static/
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # WAL + espera: vários celulares enviando ao mesmo tempo sem "database is locked"
        'OPTIONS': {
            'timeout': 20,
            'transaction_mode': 'IMMEDIATE',
            'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Pasta do app do celular (PWA), servida em /app/
PWA_DIR = Path(os.environ.get('APURA_PWA_DIR', BASE_DIR.parent / 'pwa'))

# Atrás do nginx com HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS só neste subdomínio (sem includeSubDomains/preload): fácil de desfazer zerando a variável
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', 86400))
# W008: HTTP→HTTPS é feito pelo Cloudflare antes de chegar aqui.
# W005/W021: HSTS fica restrito a este subdomínio de propósito.
SILENCED_SYSTEM_CHECKS = ['security.W008', 'security.W005', 'security.W021']

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # arquivo exportado do celular

LOGGING = {
    'version': 1,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'boletins': {'handlers': ['console'], 'level': 'INFO'}},
}
