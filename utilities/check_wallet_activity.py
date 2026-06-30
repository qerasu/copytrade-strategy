from collections import Counter
from time import gmtime, strftime

import duckdb

from utilities.analysis import find_missing_days
from utilities.defaults import (
    day_seconds,
    end,
    source,
    start,
)
from utilities.polymarket import get_activity


def check_file():
    duckdb.read_parquet(str(source)).create_view("wallet")

    # собираем показатели исходных данных до удаления дубликатов
    total, first, last = duckdb.sql(
        "SELECT count(*), min(timestamp), max(timestamp) FROM wallet"
    ).fetchone()

    unique = duckdb.sql(
        "SELECT count(*) FROM (SELECT DISTINCT * FROM wallet)"
    ).fetchone()[0]

    # проверяем количество копий каждой уникальной строки
    copies = duckdb.sql(
        """
        SELECT copies, count(*)
        FROM (
            SELECT *, count(*) AS copies
            FROM wallet
            GROUP BY ALL
        )
        GROUP BY copies
        """
    ).fetchall()

    # удаляем дубликаты до агрегации, чтобы повторы не искажали покрытие по дням
    daily = dict(
        duckdb.sql(
            f"""
            SELECT (timestamp // {day_seconds}) * {day_seconds} AS day, count(*)
            FROM (SELECT DISTINCT * FROM wallet)
            WHERE timestamp >= {start} AND timestamp < {end}
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
    )

    print(f"Rows: {total}")
    print(f"Unique rows: {unique}")
    print(f"Exact duplicates: {total - unique}")
    print(f"Row multiplicity: {dict(copies)}")

    print()

    print(
        "Time range:",
        strftime("%Y-%m-%d %H:%M:%S UTC", gmtime(first)),
        "—",
        strftime("%Y-%m-%d %H:%M:%S UTC", gmtime(last)),
    )

    print()

    print("Unique rows by UTC day:")

    for day in range(start, end, day_seconds):
        print(strftime("%Y-%m-%d", gmtime(day)), daily.get(day, 0))

    return find_missing_days(daily)


def main():
    for day in check_file():
        activity = get_activity(day)

        print()
        print(
            f"Polymarket API for {strftime('%Y-%m-%d', gmtime(day))}: "
            f"{len(activity)}"
        )
        for activity_type, count in Counter(row["type"] for row in activity).items():
            print(activity_type, count)


if __name__ == "__main__":
    main()
