# copytrade-strategy

## Запуск на macOS и Linux

Нужно положить в data/ исходные .parquet файлы

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install duckdb
python -m utilities.check_wallet_activity

python -m utilities.restore_wallet_activity # для запуска нужно удалить wallet_activity_fixed.parquet, иначе выбросится ошибка
python3 run.py
python3 -m utilities.report_metrics
```

Данные, полученные локально могут отличаться, причина описана в REPORT.md на 16 строчке.