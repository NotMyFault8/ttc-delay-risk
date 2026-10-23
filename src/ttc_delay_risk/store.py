"""Transactional publication; backfills remain invisible until explicitly released."""

import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Text,
    select,
    delete,
)


class Store:
    def __init__(self, url):
        self.engine = create_engine(url)
        schema = MetaData()
        self.batches = Table(
            "batches",
            schema,
            Column("id", String, primary_key=True),
            Column("payload", Text, nullable=False),
        )
        self.current = Table(
            "current_batches",
            schema,
            Column("date", String, primary_key=True),
            Column("batch_id", String, nullable=False),
        )
        self.runs = Table(
            "runs",
            schema,
            Column("id", String, primary_key=True),
            Column("payload", Text, nullable=False),
        )
        schema.create_all(self.engine)

    def publish(self, rows, activate=False):
        if not rows:
            raise ValueError("Cannot publish empty batch")
        keys = set()
        for row in rows:
            key = row["route_id"], row["start"]
            if key in keys or not 0 <= row["probability"] <= 1:
                raise ValueError("Invalid prediction batch")
            keys.add(key)
        payload = json.dumps(rows, sort_keys=True)
        identity = hashlib.sha256(payload.encode()).hexdigest()
        with self.engine.begin() as connection:
            if (
                connection.execute(
                    select(self.batches.c.id).where(self.batches.c.id == identity)
                ).first()
                is None
            ):
                connection.execute(
                    self.batches.insert().values(id=identity, payload=payload)
                )
            if activate:
                for day in {r["date"] for r in rows}:
                    connection.execute(
                        delete(self.current).where(self.current.c.date == day)
                    )
                    connection.execute(
                        self.current.insert().values(date=day, batch_id=identity)
                    )
        return identity

    def predictions(self, day):
        with self.engine.connect() as connection:
            result = connection.execute(
                select(self.batches.c.payload)
                .join(self.current, self.current.c.batch_id == self.batches.c.id)
                .where(self.current.c.date == day)
            ).first()
        return [r for r in json.loads(result[0]) if r["date"] == day] if result else []

    def log(self, run_id, payload):
        with self.engine.begin() as connection:
            connection.execute(delete(self.runs).where(self.runs.c.id == run_id))
            connection.execute(
                self.runs.insert().values(id=run_id, payload=json.dumps(payload))
            )
