#!/usr/bin/env python3

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone

from loguru import logger

PHASES = ["PartiallyFailed", "Failed"]


def execute(cmd):
    """Executes shell command and returns output"""

    try:
        cmd_output = subprocess.run(
            cmd.split(), capture_output=True, text=True, encoding="utf-8", check=True
        )
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed run '{cmd}' :" + str(e.stderr).replace("\n", " "))
        return ""

    return cmd_output.stdout


def find_failed_backups(window_hours) -> tuple:
    """Identifies failed backups (with associated schedules) from a list of backup
    specs within a given time window."""

    failed_backup_schedules = set()
    failed_backups = []
    current_time_utc = datetime.now(timezone.utc)

    logger.info("Fetch velero backups")
    backups_json = json.loads(execute("velero get backup -o json"))
    for backup in backups_json.get("items", []):
        status = backup.get("status", {})
        phase = status.get("phase", "")
        start_timestamp_str = status.get("startTimestamp")
        owner_references = backup.get("metadata", {}).get("ownerReferences", [])

        if start_timestamp_str is None:
            continue

        delta_time = current_time_utc - datetime.fromisoformat(
            start_timestamp_str
        ).replace(tzinfo=timezone.utc)

        if phase in PHASES and delta_time <= timedelta(hours=window_hours):

            if owner_references:
                # First check if owner reference has "Schedule" name
                for owner_ref in owner_references:
                    if owner_ref.get("kind") == "Schedule":
                        failed_backup_schedules.add(owner_ref.get("name"))
                        failed_backups.append(backup["metadata"]["name"])
            else:
                # Else check "schedule" name in labels
                failed_backup_schedules.add(
                    backup.get("metadata", {}).get("labels", {}).get("schedule", "")
                )
                failed_backups.append(backup["metadata"]["name"])

    return (failed_backup_schedules, failed_backups)


def parse_arguments():
    """Argument parser"""

    parser = argparse.ArgumentParser(
        description="A script to fetch failed Velero backups and triggers the backups manually",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-t",
        "--time-window",
        type=int,
        default="24",
        help="Time window(Hours) to look for failed backups in past",
    )
    parser.add_argument(
        "-o",
        "--dont-delete-backups",
        action="store_true",
        help="Don't delete failed backups",
    )

    return parser.parse_args()


def main():
    """Main function"""

    args = parse_arguments()

    failed_backup_schedules, failed_backups = find_failed_backups(args.time_window)
    logger.info(f"Found failed velero backups: {len(failed_backups)}")

    for schedule in failed_backup_schedules:
        output = execute(f"velero backup create --from-schedule {schedule}")
        logger.info(output.replace("\n", " "))

    if not args.dont_delete_backups:
        for backup in failed_backups:
            velero_output = execute(f"velero delete backup {backup} --confirm")
            logger.info(velero_output.replace("\n", " "))


if __name__ == "__main__":
    main()