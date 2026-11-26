import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


SHOWROOM_TZ = ZoneInfo("Asia/Kolkata")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_state():
    return {"step": "idle", "vehicle": "", "slots": []}


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self, write=False):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, language TEXT, started_at TEXT NOT NULL,
                    ended_at TEXT, state TEXT NOT NULL, summary TEXT
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, call_id TEXT NOT NULL REFERENCES calls(id),
                    role TEXT NOT NULL, text TEXT NOT NULL, language TEXT NOT NULL,
                    created_at TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
                    UNIQUE(call_id, id)
                );
                CREATE TABLE IF NOT EXISTS bookings (
                    reference TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES calls(id),
                    slot TEXT NOT NULL UNIQUE, vehicle TEXT NOT NULL, customer TEXT NOT NULL,
                    phone TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS turns_by_call ON turns(call_id, id);
                CREATE INDEX IF NOT EXISTS bookings_by_call ON bookings(call_id);
            """)
        with self.connection(write=True) as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(turns)")}
            if "generated_by" not in columns:
                db.execute("ALTER TABLE turns ADD COLUMN generated_by TEXT")

    def _turn(self, db, call_id, role, text, language, sources=(), generated_by=None):
        created_at = timestamp()
        cursor = db.execute(
            "INSERT INTO turns(call_id, role, text, language, created_at, sources, generated_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (call_id, role, text, language, created_at, json.dumps(sources, ensure_ascii=False), generated_by),
        )
        return {
            "id": cursor.lastrowid, "role": role, "text": text, "language": language,
            "created_at": created_at, "sources": list(sources), "generated_by": generated_by,
        }

    def create_call(self, language, greeting, greeting_language):
        call_id = uuid4().hex
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO calls(id, language, started_at, state) VALUES (?, ?, ?, ?)",
                (call_id, language, timestamp(), json.dumps(new_state())),
            )
            self._turn(db, call_id, "assistant", greeting, greeting_language)
        return self.call(call_id)

    @staticmethod
    def _read_turn(row):
        result = dict(row)
        result["sources"] = json.loads(result["sources"])
        return result

    def call(self, call_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["state"] = json.loads(result["state"])
            result["turns"] = [self._read_turn(turn) for turn in db.execute(
                "SELECT * FROM turns WHERE call_id = ? ORDER BY id", (call_id,)
            )]
            result["bookings"] = [dict(booking) for booking in db.execute(
                "SELECT * FROM bookings WHERE call_id = ? ORDER BY created_at", (call_id,)
            )]
            return result

    def calls(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT id, language, started_at, ended_at, summary,
                    (SELECT COUNT(*) FROM turns WHERE call_id = calls.id) AS turn_count,
                    (SELECT COUNT(*) FROM bookings WHERE call_id = calls.id) AS booking_count
                FROM calls ORDER BY started_at DESC
            """)]

    def bookings(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM bookings ORDER BY slot, customer")]

    def turn(self, turn_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
            return self._read_turn(row) if row else None

    def available_slots(self, limit=3):
        local_now = datetime.now(SHOWROOM_TZ)
        with self.connection() as db:
            booked = {row["slot"] for row in db.execute("SELECT slot FROM bookings WHERE slot >= ?", (timestamp(),))}
        slots = []
        for offset in range(1, 8):
            day = local_now.date() + timedelta(days=offset)
            for hour in (10, 12, 15, 17):
                slot = datetime.combine(day, time(hour), SHOWROOM_TZ).astimezone(timezone.utc).isoformat()
                if slot not in booked:
                    slots.append(slot)
                    if len(slots) == limit:
                        return slots
        return slots

    def save_exchange(self, call_id, user_text, user_language, language, state, answer, booking, booking_reply):
        with self.connection(write=True) as db:
            current = db.execute("SELECT ended_at FROM calls WHERE id = ?", (call_id,)).fetchone()
            if not current or current["ended_at"]:
                return False
            if booking:
                reference = f"TD-{uuid4().hex[:8].upper()}"
                slot_is_future = datetime.fromisoformat(booking["slot"]) > datetime.now(timezone.utc)
                inserted = slot_is_future and db.execute("""
                    INSERT INTO bookings(reference, call_id, slot, vehicle, customer, phone, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(slot) DO NOTHING
                """, (
                    reference, call_id, booking["slot"], booking["vehicle"],
                    booking["customer"], booking["phone"], timestamp(),
                )).rowcount == 1
                answer = booking_reply(reference if inserted else None)
            self._turn(db, call_id, "caller", user_text, user_language)
            self._turn(
                db, call_id, "assistant", answer["text"], answer["language"],
                answer.get("sources", ()), answer.get("generated_by"),
            )
            db.execute("UPDATE calls SET language = ?, state = ? WHERE id = ?", (
                language, json.dumps(state, ensure_ascii=False), call_id,
            ))
            return True

    def end_call(self, call_id):
        with self.connection(write=True) as db:
            row = db.execute("SELECT ended_at, language FROM calls WHERE id = ?", (call_id,)).fetchone()
            if not row:
                return None
            if not row["ended_at"]:
                caller_turns = db.execute(
                    "SELECT text FROM turns WHERE call_id = ? AND role = 'caller' ORDER BY id", (call_id,)
                ).fetchall()
                booking_rows = db.execute(
                    "SELECT reference, vehicle FROM bookings WHERE call_id = ? ORDER BY created_at", (call_id,)
                ).fetchall()
                if booking_rows:
                    bookings = ", ".join(f"{item['vehicle']} ({item['reference']})" for item in booking_rows)
                    summary = f"Test drive booked for {bookings}."
                elif caller_turns:
                    summary = f"Showroom enquiry. Opened with: {caller_turns[0]['text'][:180]}"
                else:
                    summary = "Session ended before the customer spoke."
                db.execute("UPDATE calls SET ended_at = ?, summary = ? WHERE id = ?", (timestamp(), summary, call_id))
        return self.call(call_id)
