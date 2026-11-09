# Defence evasion in scripts (OldSIEM runbook 09)
covers: chm-win-020, chm-win-021

Owner: whoever is on shift. Last edited: before the move (stale).

### OldSIEM alert DEF_EXCLUSION
- Rule: Defender exclusion added by PowerShell (chm-win-020). Severity high.
- Read the excluded path, it often holds the payload.
- Single field: ScriptBlockText.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

**OldSIEM alert AMSI_BYPASS**
- Rule: AMSI bypass string in a script block (chm-win-021). Severity high.
- The strings are typical of public bypass snippets.
- Single field: ScriptBlockText.
