# Persistence and accounts (OldSIEM runbook 06)
covers: chm-win-008, chm-win-010, chm-win-024

Owner: whoever is on shift. Last edited: before the move (stale).

**OldSIEM alert SCHTASK_USERDIR**
- Rule: Scheduled task created from a user folder (chm-win-008). Severity medium.
- Look at the task name and the binary path in the command line.
- TODO: stale, old tool used event 4698 here
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

OldSIEM alert NET_USER_ADD
-----
- Rule: Local account added from the command line (chm-win-010). Severity medium.
- Compare with the helpdesk change calendar.
- Fields: Image, CommandLine.

## OldSIEM alert USER_CREATED_4720
- Rule: Local user account created (chm-win-024). Severity medium.
- Compare with the helpdesk ticket for the new starter.
- Field: EventID.
