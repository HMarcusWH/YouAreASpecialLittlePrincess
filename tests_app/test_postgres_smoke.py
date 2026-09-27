"""The backend environment reaches the pinned PostgreSQL major version."""
import psycopg


def test_postgres_16_is_reachable_and_writable(database_url):
    with psycopg.connect(database_url) as conn:
        version = conn.execute("show server_version_num").fetchone()[0]
        assert 160000 <= int(version) < 170000
        conn.execute("create temporary table smoke(id int primary key)")
        conn.execute("insert into smoke values (1)")
        assert conn.execute("select count(*) from smoke").fetchone()[0] == 1
