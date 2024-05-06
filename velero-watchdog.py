#!/usr/bin/env python3

"""
A script to fetch failed Velero backups and triggers the backups manually
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from itertools import chain
from typing import Dict, List

from kubernetes import client, config
from loguru import logger

PHASES = ["PartiallyFailed", "Failed"]


def execute(cmd) -> str:
    """Executes shell command and returns output

    :parm cmd: shell command
    :type cmd: str

    :return: shell command output
    :rtype: str
    """
    logger.debug(f"Executing {cmd}")
    process = subprocess.run(
        cmd.split(), capture_output=True, text=True, check=False, encoding="utf-8"
    )
    return process.stdout


def get_failed_backup_schedules(backups_specs, window_hours) -> dict:
    """Identifies failed backups (with associated schedules) from a list of backup
    specs within a given time window.

    1. Filters backups whose backup phases are ["PartiallyFailed", "Failed"].
    2. Checks whether there are any failed backups within the given time window.
    3. Checks the "ownerReferences" of the backups with "kind" == "Schedule".
    4. Stores the "Schedule" as the key with its associated failed backups as the value."

    :param backups_spec: List of velero backups specs
    :type backups_spec: list

    :param window_hours: Time window to look failed backups
    :type window_hours: int

    :return: Dictionary of schedules with thier failed backups
    :rtype: dict
    """

    recent_failures: Dict[str, List[str]] = {}
    current_time_utc = datetime.now(timezone.utc)
    for backup in backups_specs:
        status = backup.get("status", {})
        phase = status.get("phase")
        start_timestamp_str = status.get("startTimestamp")

        if start_timestamp_str is None:
            continue

        start_timestamp = datetime.fromisoformat(status.get("startTimestamp")).replace(
            tzinfo=timezone.utc
        )

        if phase in PHASES and current_time_utc - start_timestamp <= timedelta(
            hours=window_hours
        ):
            owner_references = backup.get("metadata", {}).get("ownerReferences", [])
            for owner_ref in owner_references:
                if owner_ref.get("kind") == "Schedule":
                    schedule_name = owner_ref.get("name")
                    backup_name = backup["metadata"]["name"]
                    logger.info(
                        f"Found failed backup '{backup_name}', belongs to '{schedule_name}' "
                        f"schedule"
                    )
                    recent_failures.setdefault(schedule_name, []).append(backup_name)

    return recent_failures


def get_velero_backups() -> list:
    """Retrieves a list of Velero backup specifications using the Kubernetes client."""

    logger.info("Fetch Velero backups")
    try:
        config.load_incluster_config()
    except config.config_exception.ConfigException:
        config.load_kube_config()

    v1 = client.CustomObjectsApi()
    return v1.list_namespaced_custom_object(
        group="velero.io", version="v1", namespace="velero", plural="backups"
    )["items"]


def trigger_backup_from_schedule(schedules_list) -> list:
    """Trigger backups from given schedules

    :param failed_backup_schedules: List of schdules
    :type failed_backup_schedules: list

    :return: List of newly created backups from schedule
    :rtype: list
    """
    new_backups: List[str] = []
    for schedule in schedules_list:
        output = execute(f"velero backup create --from-schedule {schedule}")
        logger.debug(output.replace("\n", ""))

        new_bkp = re.findall(r"Backup request \"(.*?)\"", output)[0]
        new_backups.append(new_bkp)
        logger.info(f"Created new backup '{new_bkp}' from '{schedule}' schedule")

    return new_backups


def delete_backups(backups) -> None:
    """Deletes velero backups

    :param backups: List of backups
    :type backups: list

    :return: None
    """
    for backup in backups:
        output = execute(f"velero delete backup {backup} --confirm")
        logger.info(f"Deleted previously failed backup '{backup}'")
        logger.debug(output.replace("\n", ""))


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
        "-d",
        "--dry-run",
        action="store_true",
        help="Dry run mode",
    )

    parser.add_argument(
        "-e",
        "--debug",
        action="store_true",
        help="Enable debug",
    )

    parser.add_argument(
        "-o",
        "--dont-delete-backups",
        action="store_true",
        help="Don't delete failed backups",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    logger.remove()

    # Verbose option
    if args.debug:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")

    backup_specs = get_velero_backups()

    # Dry Run Option
    if args.dry_run:
        if not get_failed_backup_schedules(
            backups_specs=backup_specs, window_hours=args.time_window
        ):
            logger.info(f"No failed backups in last {args.time_window} hours")
        sys.exit()

    # No options - Default flow
    schedules = get_failed_backup_schedules(
        backups_specs=backup_specs, window_hours=args.time_window
    )
    if schedules:
        trigger_backup_from_schedule(schedules_list=schedules.keys())

        if not args.dont_delete_backups:
            # delete failed backups
            failed_backups = list(chain.from_iterable(schedules.values()))
            delete_backups(failed_backups)
    else:
        logger.info(f"No failed backups in last {args.time_window} hours")
