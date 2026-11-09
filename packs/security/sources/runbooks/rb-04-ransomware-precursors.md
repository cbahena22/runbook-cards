# Ransomware precursors (OldSIEM runbook 04)
covers: chm-win-006, chm-win-015

Owner: whoever is on shift. Last edited: before the move (stale).

## OldSIEM alert SHADOW_DELETE
- Rule: Shadow copies deleted (chm-win-006). Severity critical.
- Check the host for mass file renames after this.
- Either the vssadmin or the wmic form triggers it.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

### OldSIEM alert WEVTUTIL_CLEAR
- Rule: Event logs cleared with wevtutil (chm-win-015). Severity high.
- Pair this with the audit log cleared event on the same host.
- Fields: Image, CommandLine.
