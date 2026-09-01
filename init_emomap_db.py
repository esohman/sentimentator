#!/usr/bin/env python3
"""Create the EmoMap schema in the database selected by DATABASE_URL."""

from sqlalchemy import text

from sentimentator.app import app
from sentimentator.model import db


with app.app_context():
    db.create_all()
    journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
    foreign_keys = db.session.execute(text("PRAGMA foreign_keys")).scalar()
    print(f"Database: {db.engine.url}")
    print(f"SQLite journal_mode={journal_mode}; foreign_keys={foreign_keys}")
    print("EmoMap schema ready.")
