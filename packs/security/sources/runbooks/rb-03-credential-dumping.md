# Credential dumping (OldSIEM runbook 03)
covers: chm-win-005, chm-win-009, chm-win-016

Owner: whoever is on shift. Last edited: before the move (stale).

OldSIEM alert LSASS_DUMP_RUNDLL
-----
- Rule: Process memory dump via comsvcs (chm-win-005). Severity high.
- Often aimed at the memory of the lsass process.
- Escalate quickly, there is no usual benign cause.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

## OldSIEM alert REG_SAVE_SAM
- Rule: Registry hive saved to a file (chm-win-009). Severity high.
- The saved hive can be cracked offline.
- Check where the output file was written.

### OldSIEM alert NTDSUTIL_IFM
- Rule: Ntdsutil snapshot or media creation (chm-win-016). Severity critical.
- Only domain controllers should ever show this.
- Check the change calendar for a planned build.
