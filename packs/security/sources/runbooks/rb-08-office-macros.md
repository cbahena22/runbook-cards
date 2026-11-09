# Office macro execution (OldSIEM runbook 08)
covers: chm-win-013

Owner: whoever is on shift. Last edited: before the move (stale).

## OldSIEM alert OFFICE_SPAWN_SHELL
- Rule: Office application starts a shell (chm-win-013). Severity high.
- Ask the user what file they opened.
- Key fields: ParentImage, Image.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)
