# Repository Guidelines

## Project Structure & Module Organization
Apura BU provides unofficial election tallies from TSE ballot-report QR codes.
- `servidor/`: Django 5.2 with SQLite; `config/` contains settings and routes, while `boletins/` contains models, API views, aggregation services, migrations, and dashboard templates.
- `pwa/`: plain HTML, CSS, and JavaScript ES modules; includes IndexedDB storage, a service worker, and scanner assets in `vendor/`.
- `ferramentas/`: standalone Python decoder and real-BU validation script.
- Tests live in `servidor/boletins/tests.py`; fixtures are in `servidor/boletins/dados_teste/` and `ferramentas/`.
- Read `CLAUDE.md` for architecture and deployment details, and `README.md` for operation.

## Build, Test, and Development Commands
Run from the repository root unless specified:
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r servidor/requirements.txt
python servidor/manage.py migrate
DJANGO_DEBUG=1 python servidor/manage.py runserver
python servidor/manage.py test boletins
python3 ferramentas/teste_bus_reais.py ferramentas/bus_reais_1turno_2026.json
python3 -m http.server 8000 -d pwa
```
These commands prepare dependencies/database, start Django, run backend tests, validate decoder fixtures, and serve the standalone PWA respectively. Use paste-text input for local PWA checks. There is no frontend build, bundler, or package manager configuration.

## Coding Style & Naming Conventions
Follow surrounding code: four-space Python indentation, two-space JavaScript indentation, Python `snake_case`, JavaScript `camelCase`, and `PascalCase` classes. Preserve Portuguese domain terminology. No formatter or linter is configured.

Keep `ferramentas/bu_qrcode.py` and `servidor/boletins/bu_qrcode.py` identical. Mirror parser changes in `pwa/bu.js`; signature verification remains server-side. Bump `VERSAO` in `pwa/sw.js` after PWA changes and keep cached asset paths valid.

## Testing Guidelines
Use Django `TestCase` with `test_*` methods. Cover authentication, duplicate submissions, tampering, late certificates, imports, and tally filters when changing those behaviors. Run the decoder script for parser changes and check JavaScript parity using the Node example in `CLAUDE.md`. No coverage threshold is configured.

## Commit & Pull Request Guidelines
This directory has no Git metadata, so no historical commit convention is available. If using Git, write concise imperative subjects. PRs should explain behavior changes, report validation, link relevant issues, and include screenshots for UI changes. Update `README.md` and the team manual when workflows change.

## Security & Configuration
Keep secrets and device tokens out of commits. Settings read environment variables; consult `servidor/deploy/env.exemplo`. Preserve server-side hash/signature validation and staff-only dashboard access.
