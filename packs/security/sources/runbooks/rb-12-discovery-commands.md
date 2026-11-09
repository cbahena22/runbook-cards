# Discovery commands (OldSIEM runbook 12)
covers: chm-win-018, chm-win-019

Owner: whoever is on shift. Last edited: before the move (stale).

## OldSIEM alert NLTEST_TRUSTS
- Rule: Domain trust discovery with nltest (chm-win-018). Severity low.
- Low on its own, more interesting after other alerts on the host.
- Fields: Image, CommandLine.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

### OldSIEM alert WHOAMI_PRIV
- Rule: Local user discovery with whoami privileges (chm-win-019). Severity low.
- Common first step after a foothold.
- Fields: Image, CommandLine.
