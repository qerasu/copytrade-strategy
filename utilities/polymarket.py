import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from utilities.defaults import (
    api_limit,
    api_window_seconds,
    day_seconds,
    wallet_address,
)
from utilities.spinner import run_with_spinner


def fetch_json(request):
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def get_activity(day):
    activity = []

    # используем короткие интервалы, чтобы не превысить лимит ответа API
    for interval_start in range(day, day + day_seconds, api_window_seconds):
        for offset in range(0, 10_001, api_limit):
            params = urlencode(
                {
                    "user": wallet_address,
                    "start": interval_start,
                    "end": interval_start + api_window_seconds - 1,
                    "limit": api_limit,
                    "offset": offset,
                }
            )
            request = Request(
                f"https://data-api.polymarket.com/activity?{params}",
                headers={"User-Agent": "wallet-activity-analysis"},
            )
            page = run_with_spinner(
                "Waiting for Polymarket API...",
                fetch_json,
                request,
            )
            activity.extend(page)

            if len(page) < api_limit:
                break
        else:
            raise RuntimeError("Activity interval exceeds the API offset limit")

    return activity
