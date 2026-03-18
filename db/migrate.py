"""One-time migration: populate stocks table from existing analyses JSON blobs."""

import json
import logging

from config import settings
from db.init import open_db, upsert_stock

logger = logging.getLogger(__name__)


def migrate_analyses_to_stocks(conn) -> int:
    """Read all analyses rows and upsert a stocks row for each unique ticker.

    Returns count of rows inserted/updated.
    """
    rows = conn.execute(
        """
        SELECT ticker, company_name, json_blob
        FROM analyses
        WHERE (ticker, analysis_date) IN (
            SELECT ticker, MAX(analysis_date) FROM analyses GROUP BY ticker
        )
        """
    ).fetchall()

    count = 0
    for row in rows:
        ticker = row["ticker"]
        # Prefer the top-level company_name column; fall back to JSON blob
        name = row["company_name"]
        if not name:
            try:
                blob = json.loads(row["json_blob"])
                name = blob.get("company_name")
            except (json.JSONDecodeError, TypeError):
                pass

        upsert_stock(conn, ticker=ticker, name=name)
        count += 1
        logger.debug("Migrated stock: %s (%s)", ticker, name)

    logger.info("Migration complete: %d stocks upserted", count)
    return count


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO)
    with open_db(settings.database_url) as conn:
        count = migrate_analyses_to_stocks(conn)
        print(f"Migrated {count} stocks from analyses table.")


if __name__ == "__main__":
    main()
