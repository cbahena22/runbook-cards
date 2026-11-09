# Linux SSH and sudo (OldSIEM runbook 11)
covers: chm-lin-027, chm-lin-028

Owner: whoever is on shift. Last edited: before the move (stale).

OldSIEM alert SSH_ROOT_FAIL
-----
- Rule: SSH password failure for root (chm-lin-027). Severity medium.
- Count attempts from one source address.
- Fields: program, message.
- TODO: update screenshots for the new tool
- Old field names: proc_cmdline, src_ip, usr_name (do not use)

## OldSIEM alert SUDO_ROOT_SHELL
- Rule: Sudo used to open a root shell (chm-lin-028). Severity low.
- Check the user against the admin list.
- Fields: program, message.
