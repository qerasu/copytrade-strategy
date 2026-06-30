from utilities.defaults import day_seconds, end, start


def find_missing_days(present_days):
    return [
        day for day in range(start, end, day_seconds) if day not in present_days
    ]
