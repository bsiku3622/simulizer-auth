# Simulizer Auth Backend

**Simulizer Auth Backend** is a FastAPI server that handles authentication via Google OAuth and manages user files for the Simulizer IDE.

---

## What It Does

### Google OAuth Authentication
Sign-in and sign-out via Google OAuth 2.0. Sessions are maintained with HTTP-only JWT cookies, keeping credentials off the client.

### Account Recovery
Soft-deleted accounts enter a recovery window. Users can restore or permanently delete their account before the window expires.

### File Management
Full CRUD for user-owned Simulizer workspace files — create, read, update, delete, rename, duplicate, and thumbnail upload.

### Database Migrations
Schema migrations are managed with `yoyo-migrations` and run automatically on startup.

---

## Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI |
| Auth | Google OAuth 2.0 + JWT (python-jose) |
| Database | SQLite (via `yoyo-migrations`) |
| Runtime | Uvicorn |

---

## Requirements

- **Python** 3.11 or higher
- A Google OAuth 2.0 client (Client ID + Secret)

---

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # Fill in your credentials

python main.py                 # Runs on http://localhost:8001
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `JWT_SECRET` | Secret key for signing JWT cookies |
| `FRONTEND_URL` | Allowed CORS origin (e.g. `http://localhost:3000`) |
| `BACKEND_URL` | This server's public URL |
| `DB_PATH` | SQLite database file path |
| `FILE_STORAGE_PATH` | Directory for file storage |
| `COOKIE_SECURE` | Set `true` in production (HTTPS only) |

---

## License

This project is licensed under the **MIT License**.

For more details, see the [LICENSE](LICENSE) file.
