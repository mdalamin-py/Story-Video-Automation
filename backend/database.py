"""Database connection for SQLite development or PostgreSQL deployment."""
import os
import sqlite3


class Postgres:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row

        self.connection = psycopg.connect(url, autocommit=True, row_factory=dict_row)

    def execute(self, statement, parameters=()):
        return self.connection.execute(statement.replace("?", "%s"), parameters)

    def commit(self):
        self.connection.execute("COMMIT")

    def close(self):
        self.connection.close()


def database(path):
    url = os.environ.get("STUDIO_DATABASE_URL")
    if url:
        return Postgres(url)
    connection = sqlite3.connect(path, timeout=20, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection
