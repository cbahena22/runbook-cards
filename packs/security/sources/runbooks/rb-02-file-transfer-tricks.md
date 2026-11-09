# File transfer tricks (OldSIEM runbook 02)
covers: chm-win-003, chm-win-004

Owner: whoever is on shift. Last edited: before the move (stale).

**OldSIEM alert CERTUTIL_DL**
- Rule: Certutil used to fetch a file (chm-win-003). Severity high.
- certutil is normally for certificates, not downloads.
- Key fields: Image, CommandLine (urlcache or verifyctl).
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

OldSIEM alert BITS_JOB
-----
- Rule: Bitsadmin transfer job (chm-win-004). Severity medium.
- BITS jobs survive a reboot, so ask about persistence.
- Fields: Image, CommandLine.
