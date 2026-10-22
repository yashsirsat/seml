# Database Configuration Update

## Plan Steps:
- [x] Update app.py with env-aware DB config (Vercel/Neon + SQLite fallback)
- [x] Test app startup and DB connection
- [x] Verify models/tables in new DB (no errors on startup)
- [ ] Data migration if needed (SQLite -> Postgres)
- [ ] Update Vercel deployment if successful

Current: Step 1 & 2 complete - app.py updated, server starts successfully on http://127.0.0.1:5000 with no DB errors (db.create_all() passed).
