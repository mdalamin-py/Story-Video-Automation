"""Run in a separate process. Pending jobs survive process restarts."""
import argparse
import time

from backend.jobs import claim, deliver_one, heartbeat, produce


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        heartbeat("local")
        row = claim()
        if row:
            produce(row)
        published = deliver_one()
        if args.once:
            return
        if not row and not published:
            time.sleep(1)


if __name__ == "__main__":
    main()
