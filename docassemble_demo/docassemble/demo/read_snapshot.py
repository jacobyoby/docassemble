# do not pre-load
from docassemble.base.util import variables_snapshot_connect, current_context

__all__ = ['analyze']


def analyze():
    with variables_snapshot_connect() as conn:
        with conn.connection.cursor() as cur:
            # NB: parameterized, never interpolated (M-16). The DBAPI cursor
            # here is psycopg2 (pyformat %s style); the filename comes from
            # the interview context and must not reach SQL as text.
            cur.execute("select data->>'favorite_fruit' from jsonstorage where filename=%s", (current_context().filename,))
            counts = {}
            for record in cur.fetchall():
                fruit = record[0].lower()
                if fruit not in counts:
                    counts[fruit] = 0
                counts[fruit] += 1
    return counts
