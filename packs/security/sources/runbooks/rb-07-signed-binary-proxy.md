# Signed binary proxy execution (OldSIEM runbook 07)
covers: chm-win-011, chm-win-012

Owner: whoever is on shift. Last edited: before the move (stale).

OldSIEM alert MSHTA_REMOTE
-----
- Rule: Mshta running remote content (chm-win-011). Severity high.
- mshta should almost never reach the internet.
- Pull the address from CommandLine.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

## OldSIEM alert REGSVR_SCRIPTLET
- Rule: Regsvr32 loading a scriptlet (chm-win-012). Severity high.
- Look for /i: pointing at a remote file.
- Fields: Image, CommandLine.
