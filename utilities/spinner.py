from concurrent.futures import ThreadPoolExecutor
from itertools import cycle
from time import sleep


def run_with_spinner(message, function, *args, **kwargs):
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(function, *args, **kwargs)
        for frame in cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            if future.done():
                break
            print(f"\r{frame} {message}", end="", flush=True)
            sleep(0.08)
        print("\r" + " " * (len(message) + 2), end="\r")

        return future.result()
