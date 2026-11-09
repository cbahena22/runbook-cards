# Logon events (OldSIEM runbook 10)
covers: chm-win-023, chm-win-026

Owner: whoever is on shift. Last edited: before the move (stale).

**OldSIEM alert FAILED_NET_LOGON**
- Rule: Failed network logon (chm-win-023). Severity low.
- One event is noise. Count them per source and account.
- Fields: EventID, LogonType.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

OldSIEM alert RDP_LOGON
-----
- Rule: Remote desktop logon (chm-win-026). Severity low.
- Look at the source address and the time of day.
- Fields: EventID, LogonType.
