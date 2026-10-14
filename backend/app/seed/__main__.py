import sys

from app.core.db import SessionLocal, init_db, reset_db
from app.seed import seed_all, seed_if_empty

if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_db()
        with SessionLocal() as db:
            seed_all(db)
        print("Database reset and demo data loaded.")
    else:
        init_db()
        with SessionLocal() as db:
            loaded = seed_if_empty(db)
        print("Demo data loaded." if loaded else "Database already has data; use --reset to reload.")
