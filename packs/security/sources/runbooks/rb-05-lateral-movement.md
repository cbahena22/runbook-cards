# Lateral movement (OldSIEM runbook 05)
covers: chm-win-007, chm-win-014

Owner: whoever is on shift. Last edited: before the move (stale).

### OldSIEM alert WMIC_PROC_CREATE
- Rule: WMIC remote process creation (chm-win-007). Severity medium.
- If /node: is present the target is another host.
- Fields: Image, CommandLine.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

**OldSIEM alert PSEXEC_SVC**
- Rule: PsExec service binary started (chm-win-014). Severity medium.
- Check who ran PsExec and from which host.
- Only field used: Image.
