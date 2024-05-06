# Velero Watchdog Script
A script to fetch failed Velero backups and triggers the backup manually

## Usage
```bash
$ ./velero-watchdog.py -h
usage: velero-watchdog.py [-h] [-t TIME_WINDOW] [-d] [-e] [-o]

A script to fetch failed Velero backups and triggers the backups manually

options:
  -h, --help            show this help message and exit
  -t TIME_WINDOW, --time-window TIME_WINDOW
                        Time window(Hours) to look for failed backups in past (default: 24)
  -d, --dry-run         Dry run mode (default: False)
  -e, --debug           Enable debug (default: False)
  -o, --dont-delete-backups
                        Don't delete failed backups (default: False)
```
