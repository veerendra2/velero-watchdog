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


class KubernetesAPI:
    """Kubernetes Client"""

    def __init__(self):
        logger.info("Access Kubernetes API")
        try:
            config.load_incluster_config()
        except config.config_exception.ConfigException:
            config.load_kube_config()

        self.v1 = client.CustomObjectsApi()

    def get_velero_backups(self) -> list:
        """Gets velero backup

        :return: list of velero backup k8s specs
        :rtype: list
        """

        logger.debug("Fetch velero backups K8s specs")
        return self.v1.list_namespaced_custom_object(
            group="velero.io", version="v1", namespace="velero", plural="backups"
        )["items"]

    def delete_velero_backups(self, backup_name):
        """Delete velero backups

        :parm backup_name: backups list to be deleted
        :type backup_name: list
        """

        logger.debug(f"Delete velero backup K8s spec '{backup_name}'")
        self.v1.delete_namespaced_custom_object(
            group="velero.io",
            version="v1",
            namespace="velero",
            plural="backups",
            name=backup_name,
        )


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


def find_failed_backup_schedules(backups_specs, window_hours) -> dict:
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

        start_timestamp = datetime.fromisoformat(start_timestamp_str).replace(
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


def trigger_backups_from_schedules(schedules_list) -> list:
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


def delete_backups(backups, k8s_obj) -> None:
    """Helper function to delete Velero backup with velero cli and K8s API

    :param backups: List of backups
    :type backups: list
    :param k8s: Kubernetes client object
    :type k8s: kubernetes.client.api.custom_objects_api.CustomObjectsApi

    :return: None
    """
    for backup in backups:
        logger.info(f"Delete previously failed backup '{backup}'")
        velero_output = execute(f"velero delete backup {backup} --confirm")

        # also delete K8s spec
        k8s_obj.delete_velero_backups(backup)
        logger.debug(velero_output.replace("\n", ""))


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


def main():
    """Main function"""

    args = parse_arguments()

    # Verbose
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if args.debug else "INFO")

    k8s = KubernetesAPI()
    backup_specs = k8s.get_velero_backups()

    schedules = find_failed_backup_schedules(
        backups_specs=backup_specs, window_hours=args.time_window
    )

    if not schedules:
        logger.info(f"No failed backups in last {args.time_window} hours")
        return

    if args.dry_run:
        return

    # Trigger new backups from schedules
    trigger_backups_from_schedules(schedules_list=schedules.keys())

    if not args.dont_delete_backups:
        # Delete failed backups
        delete_backups(list(chain.from_iterable(schedules.values())), k8s)


if __name__ == "__main__":
    main()
