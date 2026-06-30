from datetime import datetime, timezone
from pathlib import Path


wallet_address = "0xa6657ab4eb9d92c8bbfb1d1d52ce7205e4ca01e3"
source = Path("data/wallet_activity.parquet")
output = Path("data/wallet_activity_fixed.parquet")
start = int(datetime(2026, 6, 11, tzinfo=timezone.utc).timestamp())
end = int(datetime(2026, 6, 18, tzinfo=timezone.utc).timestamp())
day_seconds = 86400
api_window_seconds = 21600
api_limit = 500
