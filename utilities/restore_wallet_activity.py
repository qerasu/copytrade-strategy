import duckdb

from utilities.defaults import (
    day_seconds,
    end,
    output,
    source,
    start,
)
from utilities.polymarket import get_activity


def main():
    if output.exists():
        raise FileExistsError(f"{output} already exists")

    duckdb.read_parquet(str(source)).create_view("wallet")
    activity = [
        row
        for day in range(start, end, day_seconds)
        for row in get_activity(day)
    ]

    columns = [row[0] for row in duckdb.sql("DESCRIBE wallet").fetchall()]
    duckdb.execute("CREATE TEMP TABLE fixed_wallet AS SELECT DISTINCT * FROM wallet")
    if activity:
        placeholders = ", ".join("?" for _ in columns)
        duckdb.executemany(
            f"INSERT INTO fixed_wallet VALUES ({placeholders})",
            [tuple(row.get(column) for column in columns) for row in activity],
        )

    # повторно удаляем дубликаты на случай пересечения интервалов API
    duckdb.execute(
        "CREATE TEMP VIEW corrected_wallet AS SELECT DISTINCT * FROM fixed_wallet"
    )

    rows, trades, markets = duckdb.sql(
        """
        SELECT count(*),
               count(*) FILTER (WHERE type = 'TRADE'),
               count(DISTINCT conditionId) FILTER (WHERE type = 'TRADE')
        FROM corrected_wallet
        """
    ).fetchone()

    duckdb.execute(
        f"""
        COPY (
            SELECT * FROM corrected_wallet
            ORDER BY timestamp, transactionHash
        ) TO '{output}' (FORMAT PARQUET)
        """
    )

    print(f"Saved: {output}")
    print(f"Rows: {rows}; trades: {trades}; markets: {markets}")


if __name__ == "__main__":
    main()
