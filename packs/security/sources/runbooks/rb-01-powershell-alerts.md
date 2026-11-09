# PowerShell alerts (OldSIEM runbook 01)
covers: chm-win-001, chm-win-002

Owner: whoever is on shift. Last edited: before the move (stale).

### OldSIEM alert PS_ENCODED_CMD
- Rule: Encoded PowerShell command line (chm-win-001). Severity medium.
- Fires when powershell.exe or pwsh.exe runs with -enc or -EncodedCommand.
- Decode the blob (base64, UTF-16LE) and read it before judging.
- Check proc_cmdline (old field name) and the parent process.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

**OldSIEM alert PS_DL_CRADLE**
- Rule: PowerShell download cradle (chm-win-002). Severity high.
- Look at the URL host first. Is it internal?
- The rule needs DownloadString, Invoke-WebRequest or IEX in CommandLine.
- TODO add allowlist for the patch server
