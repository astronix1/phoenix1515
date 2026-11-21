# Contributing

## Local setup

Create a virtual environment and install dependencies:

```sh
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

## Validate changes

Check the seed data and run the unit tests:

```sh
python scripts/dev.py validate
python scripts/dev.py test
python scripts/dev.py environment
```

## Useful utilities

- `python scripts/check_environment.py` checks common local configuration and port availability.
- `python scripts/backup_sqlite.py --source shop.db --destination backups` creates a consistent SQLite backup.
- `python scripts/export_catalog.py --output catalog.json --format json` exports the seed catalogue.
- `python scripts/export_catalog.py --category Electronics --format csv --output electronics.csv` exports a filtered CSV.

## Commit guidance

Keep commits focused, describe the user-visible or developer-visible change, and include tests for behavior changes. Do not commit `.env`, SQLite databases, generated vector indexes, or backup files.
