import argparse
from os import getenv
import sys

from raven_framework import RunApp

from nail_ar.app import NailAR


def main():
    parser = argparse.ArgumentParser(description="Launch Nail AR on Raven.")
    parser.add_argument("--demo", action="store_true", help="Use sample inventory and suggest an optional 15-second timer.")
    parser.add_argument("--dry-seconds", type=int, help="Initial optional drying duration in seconds.")
    parser.add_argument("--narrate", action="store_true", help="Read instructions aloud when speech is available.")
    options, raven_args = parser.parse_known_args()
    if options.dry_seconds is not None and options.dry_seconds < 1:
        parser.error("--dry-seconds must be a positive integer")
    duration = options.dry_seconds or (15 if options.demo else 900)
    sys.argv[1:] = raven_args
    RunApp.run(
        lambda: NailAR(options.demo, duration, options.narrate),
        app_id=getenv("RAVEN_APP_ID", ""),
        app_key=getenv("RAVEN_APP_KEY", ""),
    )


if __name__ == "__main__":
    main()
