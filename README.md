<p align="center">
  <img src="app/static/images/mbc-watermark.png" alt="Malawi Broadcasting Corporation" width="110">
</p>

<h1 align="center">MBC Raffle Draw System</h1>

<p align="center">
  Run live, on-air prize draws for Malawi Broadcasting Corporation promotions, from collecting entries to revealing winners on screen.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.13-1f2937">
  <img alt="Flask" src="https://img.shields.io/badge/flask-3.1-1f2937">
  <img alt="Status" src="https://img.shields.io/badge/status-in%20development-c8102e">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-1f2937">
</p>

---

## What it does

| Area | Description |
|------|-------------|
| **Draws and prizes** | Create a draw with one or more prizes (cash, goods, vouchers, services), each with a quantity and a draw order. |
| **Participants** | Collect entrants' phone numbers from CSV/Excel uploads, manual entry, or by polling an external API (e.g. an SMS shortcode platform). |
| **Live draw** | Operators start, pause and resume a draw, then draw winners one at a time. Winners are chosen with a cryptographically secure random generator, and nobody can win twice in the same draw. |
| **TV display** | A full-screen `/tv` page for broadcast: spinning-number animation and a winner reveal, with phone numbers masked (`0999***456`). |
| **Winner handling** | Void a winner who can't be reached or isn't eligible. Their prize goes back into the draw for a redraw. |
| **Accountability** | Role-based login (admin / operator) and an audit log of every action, with sensitive fields redacted. |

## Tech stack

- **Backend:** Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-Migrate (Alembic)
- **Database:** SQLite by default; any SQLAlchemy URL via `DATABASE_URL`
- **Imports:** pandas and openpyxl for spreadsheet uploads
- **Frontend:** server-rendered Jinja templates with vanilla JavaScript

## Getting started

**Prerequisites:** Python 3.13 and Git.

```bash
git clone <repository-url>
cd raffle_draw_system

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Configure

Copy the example environment file and set a secret key:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste into SECRET_KEY
```

| Variable | Purpose | Default |
|----------|---------|---------|
| `APP_ENV` | `development` or `production` | `development` |
| `SECRET_KEY` | Session signing key. **Required.** The app refuses to start without it. | none |
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///raffle_system.db` |
| `HOST` | Interface to bind when using `python run.py` | `127.0.0.1` |

### Set up the database and an admin user

```bash
flask --app run db upgrade
flask --app run create-admin <username>      # prompts for a password
```

### Run

```bash
python run.py
```

| Page | URL |
|------|-----|
| Operator console | http://127.0.0.1:5025/ |
| Admin panel | http://127.0.0.1:5025/admin |
| Participants | http://127.0.0.1:5025/participants |
| TV display (live draw) | http://127.0.0.1:5025/tv |
| TV display (specific draw) | http://127.0.0.1:5025/tv/&lt;draw_id&gt; |

## Project structure

```
app/
├── models/        # SQLAlchemy models: draws, prizes, participants, winners, users, API config
├── services/      # Business logic: draw engine, prize parsing, imports, API polling
├── routes/        # Flask blueprints: auth, admin, draws, participants, TV
├── utils/         # Security, phone masking, file processing
├── templates/     # Jinja templates
└── static/        # CSS, JavaScript, MBC brand assets
migrations/        # Alembic database migrations
run.py             # Entry point
```

## Running a draw

1. **Admin** creates a draw and adds its prizes.
2. Participants are loaded through an upload or the API feed, then verified.
3. **Operator** opens the TV display on the broadcast screen and starts the draw.
4. Winners are drawn one by one in prize order. The draw closes automatically when every prize has a winner.
5. If a winner can't be reached, an admin voids them and that prize is drawn again.

Only one draw can be live at a time. A draw can't start until it has enough verified participants for its remaining prizes.

## Project status

The system is being reworked from a single-cash-prize model to multiple prizes per draw, with logic moved into a service layer. Until that work is merged, some screens may still use the old endpoints. See the open issues and pull requests for current progress.

## Transparency

These draws decide who receives money and prizes, so the code is public on purpose. Anyone can read exactly how winners are chosen. The selection logic is in [`app/services/draw_service.py`](app/services/draw_service.py).

## Contributing

**Branching model**

| Branch | Role |
|--------|------|
| `master` | Production. Updated **only** by merging `develop`. |
| `develop` | Integration branch. Every feature or fix branch starts here and merges back here. |
| `feature/<short-name>`, `fix/<short-name>` | Day-to-day work, branched from `develop`. |

1. Branch from `develop` and open your pull request against `develop`.
2. For any model change, generate a migration: `flask --app run db migrate -m "describe change"`, then review the generated file.
3. Never commit `.env`, databases or uploaded files. `.gitignore` already covers them.
4. A release is a pull request from `develop` into `master`. No other branch merges into `master`.

## License

Released under the [MIT License](LICENSE).

---

<p align="center">
  <sub>© 2026 Malawi Broadcasting Corporation</sub>
</p>
