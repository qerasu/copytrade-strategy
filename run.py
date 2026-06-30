from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import duckdb

from utilities.spinner import run_with_spinner


wallet_activity = Path("data/wallet_activity_fixed.parquet")
orderbooks = Path("data/clob_orderbook_history.parquet")
outcomes = Path("data/market_outcomes.parquet")
crypto_taker_fee_rate = Decimal("0.07")


def fill_book(asks, requested_size):
    remaining = Decimal(str(requested_size))
    filled = Decimal()
    cost = Decimal()
    fee = Decimal()

    for level in sorted(asks or [], key=lambda row: Decimal(row["price"])):
        price = Decimal(level["price"])
        size = min(remaining, Decimal(level["size"]))
        if size <= 0:
            continue

        filled += size
        cost += size * price
        # для crypto-рынков taker-комиссия симметрична относительно цены 0.5
        fee += (size * crypto_taker_fee_rate * price * (1 - price)).quantize(
            Decimal("0.00001"),
            rounding=ROUND_HALF_UP,
        )
        remaining -= size
        if remaining == 0:
            break

    return filled, cost, fee


def load_rows(path):
    relation = duckdb.read_parquet(str(path))
    return [dict(zip(relation.columns, row)) for row in relation.fetchall()]


def match_orderbooks(trades, delays_ms):
    executions = [
        (
            execution_id,
            trade["conditionId"],
            trade["asset"],
            trade["timestamp"] * 1000 + delay_ms,
            delay_ms,
        )
        for execution_id, trade in enumerate(trades)
        for delay_ms in delays_ms
    ]
    if not executions:
        return {}

    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TEMP TABLE executions (
                execution_id BIGINT,
                market VARCHAR,
                asset_id VARCHAR,
                timestamp BIGINT,
                delay_ms INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO executions VALUES (?, ?, ?, ?, ?)",
            executions,
        )

        # asof join сопоставляет исполнение с последним более ранним состоянием
        rows = connection.execute(
            f"""
            WITH relevant_markets AS (
                SELECT DISTINCT market, asset_id
                FROM executions
            ),
            books AS (
                SELECT b.market, b.asset_id, b.timestamp, b.asks
                FROM read_parquet('{orderbooks}') b
                JOIN relevant_markets r USING (market, asset_id)
            )
            SELECT e.execution_id, e.delay_ms, b.timestamp, b.asks
            FROM executions e
            ASOF LEFT JOIN books b
              ON e.market = b.market
             AND e.asset_id = b.asset_id
             AND e.timestamp > CAST(b.timestamp AS BIGINT)
            """
        ).fetchall()

    missing = sum(timestamp is None for _, _, timestamp, _ in rows)
    if missing:
        raise RuntimeError(
            f"No prior order book snapshot for {missing} trade scenarios"
        )

    matched = {
        (execution_id, delay_ms): (int(timestamp), asks)
        for execution_id, delay_ms, timestamp, asks in rows
    }

    return matched


def simulate(trades, winners, matched, delay_ms, size_multiplier):
    cost_total = Decimal()
    fee_total = Decimal()
    payout_total = Decimal()

    for execution_id, trade in enumerate(trades):
        _, asks = matched[(execution_id, delay_ms)]
        requested_size = Decimal(str(trade["size"])) * size_multiplier
        filled, cost, fee = fill_book(asks, requested_size)
        payout = filled if trade["asset"] == winners[trade["conditionId"]] else Decimal()

        cost_total += cost
        fee_total += fee
        payout_total += payout

    pnl_before_fees = payout_total - cost_total
    pnl_after_fees = pnl_before_fees - fee_total
    spent = cost_total + fee_total
    roi = pnl_after_fees / spent if spent else Decimal()

    return pnl_before_fees, fee_total, pnl_after_fees, roi


def main():
    # мини тест
    check = fill_book(
        [{"price": "0.50", "size": "3"}, {"price": "0.40", "size": "2"}],
        4,
    )

    assert check == (Decimal("4"), Decimal("1.80"), Decimal("0.06860"))
    assert simulate([], {}, {}, 0, Decimal("1")) == (Decimal(),) * 4

    trades = [
        row
        for row in load_rows(wallet_activity)
        if row["type"] == "TRADE" and row["side"] == "BUY"
    ]

    winners = {
        row["condition_id"]: row["winning_token_id"] for row in load_rows(outcomes)
    }

    scenarios = [
        ("delay 0s", 0, Decimal("1")),
        ("baseline", 1_000, Decimal("1")),
        ("delay 3s", 3_000, Decimal("1")),
        ("size 0.5x", 1_000, Decimal("0.5")),
        ("size 2x", 1_000, Decimal("2")),
    ]
    delays_ms = {delay_ms for _, delay_ms, _ in scenarios}
    matched = run_with_spinner(
        "Matching order books...",
        match_orderbooks,
        trades,
        delays_ms,
    )

    border = f"+{'-' * 11}+{'-' * 13}+{'-' * 11}+{'-' * 13}+{'-' * 9}+"
    print(border)
    print(
        f"|{'Scenario':^11}|{'P&L before':^13}|{'Fees':^11}|"
        f"{'P&L after':^13}|{'ROI':^9}|"
    )
    print(border)
    for name, delay_ms, size_multiplier in scenarios:
        before, fees, after, roi = simulate(
            trades,
            winners,
            matched,
            delay_ms,
            size_multiplier,
        )
        print(
            f"|{name:<11}|{f'${before:.2f}':>13}|{f'${fees:.2f}':>11}|"
            f"{f'${after:.2f}':>13}|{roi:>9.2%}|"
        )
    print(border)


if __name__ == "__main__":
    main()
