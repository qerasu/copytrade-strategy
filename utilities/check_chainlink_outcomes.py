from pathlib import Path

import duckdb


outcomes = Path("data/market_outcomes.parquet")
prices = Path("data/btc_chainlink_prices.parquet")


def get_stats():
    return duckdb.sql(
        f"""
        WITH oracle_prices AS (
            SELECT ts_ms, mid
            FROM read_parquet('{prices}')
        ),
        checks AS (
            SELECT
                outcome.winning_outcome,
                start_price.mid AS start_price,
                end_price.mid AS end_price,
                CASE
                    WHEN end_price.mid >= start_price.mid THEN 'Up'
                    ELSE 'Down'
                END AS expected_outcome
            FROM read_parquet('{outcomes}') outcome
            LEFT JOIN oracle_prices start_price
                ON start_price.ts_ms = outcome.start_ts_ms
            LEFT JOIN oracle_prices end_price
                ON end_price.ts_ms = outcome.end_ts_ms
        )
        SELECT
            count(*),
            count(*) FILTER (
                WHERE start_price IS NOT NULL AND end_price IS NOT NULL
            ),
            count(*) FILTER (
                WHERE start_price IS NOT NULL
                  AND end_price IS NOT NULL
                  AND winning_outcome = expected_outcome
            ),
            count(*) FILTER (
                WHERE start_price IS NOT NULL
                  AND end_price IS NOT NULL
                  AND winning_outcome <> expected_outcome
            )
        FROM checks
        """
    ).fetchone()


def main():
    total, covered, matches, mismatches = get_stats()

    assert covered == matches + mismatches

    print(f"Markets: {total}")
    print(f"Covered by Chainlink prices: {covered}")
    print(f"Missing boundary prices: {total - covered}")
    print(f"Matches: {matches}")
    print(f"Mismatches: {mismatches}")
    print(f"Match rate on covered markets: {matches / covered:.2%}")


if __name__ == "__main__":
    main()
