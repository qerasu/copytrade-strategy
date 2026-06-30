# copytrade-strategy

## Запуск на macOS и Linux

Нужно пололжить в data/ исходные .parquet файлы

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install duckdb
python -m utilities.check_wallet_activity
python -m utilities.restore_wallet_activity
python3 run.py
python3 -m utilities.report_metrics
```
