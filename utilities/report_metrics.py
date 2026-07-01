from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import duckdb

from run import fill_book, load_rows, match_orderbooks, outcomes, wallet_activity
from utilities.check_chainlink_outcomes import get_stats


source = "data/wallet_activity.parquet"
fixed = "data/wallet_activity_fixed.parquet"
prices = "data/btc_chainlink_prices.parquet"


def print_query(title, sql):
    print(f"\n{title}")
    for row in duckdb.sql(sql).fetchall():
        print(*row)


def print_daily(title, path):
    print(f"\n{title}")
    rows = duckdb.sql(
        f"""
        SELECT timestamp // 86400 * 86400 AS day_start, count(*)
        FROM (SELECT DISTINCT * FROM read_parquet('{path}'))
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    for day_start, count in rows:
        date = datetime.fromtimestamp(day_start, timezone.utc).date().isoformat()
        print(date, count)


def print_simulation():
    activity = load_rows(wallet_activity)
    trades = [
        row
        for row in activity
        if row["type"] == "TRADE" and row["side"] == "BUY"
    ]

    redeemed_at = {
        row["conditionId"]: row["timestamp"] * 1000
        for row in activity
        if row["type"] == "REDEEM"
    }
    trading_ended_at = max(
        trade["timestamp"] * 1000 + 1_000 for trade in trades
    )

    market_rows = load_rows(outcomes)
    winners = {row["condition_id"]: row["winning_token_id"] for row in market_rows}
    ends = {row["condition_id"]: row["end_ts_ms"] for row in market_rows}
    matched = match_orderbooks(trades, {1_000})
    daily = defaultdict(Decimal)
    markets = defaultdict(Decimal)
    cost_total = Decimal()
    fee_total = Decimal()
    payout_total = Decimal()
    cash_flows = []

    for index, trade in enumerate(trades):
        _, asks = matched[(index, 1_000)]
        filled, cost, fee = fill_book(asks, trade["size"])
        payout = (
            filled
            if trade["asset"] == winners[trade["conditionId"]]
            else Decimal()
        )
        pnl = payout - cost - fee
        resolved_at = ends[trade["conditionId"]]
        date = datetime.fromtimestamp(
            resolved_at / 1000,
            timezone.utc,
        ).date().isoformat()

        cost_total += cost
        fee_total += fee
        payout_total += payout
        daily[date] += pnl
        markets[trade["conditionId"]] += pnl
        cash_flows.append((trade["timestamp"] * 1000 + 1_000, 0, -cost - fee))

        payout_at = redeemed_at.get(
            trade["conditionId"],
            max(trading_ended_at, resolved_at),
        )
        cash_flows.append((payout_at, 1, payout))

    before = payout_total - cost_total
    after = before - fee_total
    roi = after / (cost_total + fee_total)
    assert after == sum(daily.values()) == sum(markets.values())
    assert after == sum(amount for _, _, amount in cash_flows)

    print("\nBASELINE SIMULATION")
    print(f"P&L before fees: ${before:.2f}")
    print(f"Fees: ${fee_total:.2f}")
    print(f"P&L after fees: ${after:.2f}")
    print(f"ROI: {roi:.2%}")

    print("\nDAILY AND CUMULATIVE P&L")
    cumulative = Decimal()
    for date, pnl in sorted(daily.items()):
        cumulative += pnl
        print(date, f"daily=${pnl:.2f}", f"cumulative=${cumulative:.2f}")

    equity = Decimal()
    peak = Decimal()
    max_drawdown = Decimal()
    for market, pnl in sorted(
        markets.items(),
        key=lambda item: (ends[item[0]], item[0]),
    ):
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    cash_balance = Decimal()
    minimum_balance = Decimal()
    for _, _, amount in sorted(cash_flows):
        cash_balance += amount
        minimum_balance = min(minimum_balance, cash_balance)

    initial_deposit = -minimum_balance
    drawdown_percent = max_drawdown / initial_deposit

    print(f"\nInitial deposit required: ${initial_deposit:.2f}")
    print(
        f"Maximum drawdown: ${max_drawdown:.2f} "
        f"({drawdown_percent:.2%} of initial deposit)"
    )


def main():
    print_daily("ORIGINAL UNIQUE ROWS BY UTC DAY", source)
    print_daily("RESTORED ROWS BY UTC DAY", fixed)
    print_query(
        "RESTORED FILE",
        f"""
        SELECT
            count(*) AS rows,
            count(*) FILTER (WHERE type = 'TRADE') AS trades,
            count(DISTINCT conditionId) FILTER (
                WHERE type = 'TRADE'
            ) AS markets
        FROM read_parquet('{fixed}')
        """,
    )

    print_simulation()

    total, covered, matches, _ = get_stats()
    print("\nCHAINLINK CHECK")
    print(total, covered, matches)

    print_query(
        "WALLET BEHAVIOR",
        f"""
        WITH trades AS (
            SELECT *
            FROM read_parquet('{fixed}')
            WHERE type = 'TRADE'
        ),
        per_market AS (
            SELECT
                conditionId,
                count(*) AS trade_count,
                count(DISTINCT outcome) AS outcome_count,
                CASE
                    WHEN count(DISTINCT outcome) = 1 THEN min(outcome)
                END AS selected_outcome
            FROM trades
            GROUP BY 1
        )
        SELECT
            (SELECT count(*) FROM trades) AS trades,
            (SELECT count(*) FROM read_parquet('{fixed}')
             WHERE type = 'REDEEM') AS redeems,
            count(*) FILTER (WHERE selected_outcome = 'Up') AS up_markets,
            count(*) FILTER (WHERE selected_outcome = 'Down') AS down_markets,
            count(*) FILTER (WHERE outcome_count > 1) AS mixed_markets,
            round(avg(trade_count), 2) AS average_trades,
            median(trade_count) AS median_trades,
            min(trade_count) AS minimum_trades,
            max(trade_count) AS maximum_trades
        FROM per_market
        """,
    )
    print_query(
        "ENTRY TIME",
        f"""
        WITH entries AS (
            SELECT outcome.end_ts_ms / 1000 - trade.timestamp AS seconds_left
            FROM read_parquet('{fixed}') trade
            JOIN read_parquet('data/market_outcomes.parquet') outcome
              ON trade.conditionId = outcome.condition_id
            WHERE trade.type = 'TRADE'
        )
        SELECT
            round(avg(seconds_left), 2) AS average_seconds,
            median(seconds_left) AS median_seconds,
            count(*) FILTER (
                WHERE seconds_left >= 0 AND seconds_left < 60
            ) AS under_one_minute,
            count(*) FILTER (
                WHERE seconds_left >= 60 AND seconds_left < 300
            ) AS one_to_five_minutes,
            count(*) FILTER (WHERE seconds_left >= 300) AS over_five_minutes,
            count(*) FILTER (WHERE seconds_left < 0) AS after_close
        FROM entries
        """,
    )
    print_query(
        "TOKEN PRICES",
        f"""
        SELECT outcome, round(avg(price), 4), median(price)
        FROM read_parquet('{fixed}')
        WHERE type = 'TRADE'
        GROUP BY 1
        ORDER BY 1
        """,
    )
    print_query(
        "MOMENTUM CHECK",
        f"""
        WITH oracle_prices AS (
            SELECT ts_ms, mid
            FROM read_parquet('{prices}')
        )
        SELECT
            count(*) AS covered,
            count(*) FILTER (
                WHERE trade.outcome = CASE
                    WHEN entry_price.mid >= start_price.mid THEN 'Up'
                    ELSE 'Down'
                END
            ) AS follows_direction,
            round(
                100.0 * count(*) FILTER (
                    WHERE trade.outcome = CASE
                        WHEN entry_price.mid >= start_price.mid THEN 'Up'
                        ELSE 'Down'
                    END
                ) / count(*),
                2
            ) AS percent
        FROM read_parquet('{fixed}') trade
        JOIN read_parquet('data/market_outcomes.parquet') outcome
          ON trade.conditionId = outcome.condition_id
        JOIN oracle_prices start_price
          ON start_price.ts_ms = outcome.start_ts_ms
        JOIN oracle_prices entry_price
          ON entry_price.ts_ms = trade.timestamp * 1000
        WHERE trade.type = 'TRADE'
        """,
    )


if __name__ == "__main__":
    main()
