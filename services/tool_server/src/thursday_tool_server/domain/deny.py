"""Shell commands that are never run, whoever approves them.

Approval is the control for the shell, and an "always allow" rule removes it for a chat. This list is the
part that cannot be switched off: commands that destroy data beyond the project, weaken the PC's security,
or move files to or from another machine.

It reads the command as text. It catches the plain forms of these commands, which is what a model writes; it is
not a sandbox, and a command hidden inside a script file or built up from pieces is not seen. Commands that hide
their own text (an encoded command, text decoded and then run) are refused for that reason.
"""

import re

_FLAGS = re.IGNORECASE


def _word(names: str) -> str:
    """One of the names as a whole command word (`curl`, not `curly` or `my-curl`)."""
    return rf"(?<![\w.\-\\/])(?:{names})(?:\.exe)?(?![\w\-])"


_DELETE = re.compile(_word(r"remove-item|rm|ri|del|erase|rd|rmdir"), _FLAGS)
# A place that is not inside the project folder: a drive or share, the home folder, a variable, or a step up.
_OUTSIDE = re.compile(r"[a-z]:[\\/]|\\\\|(?<![\w.])~|\$env:|\$home\b|\$\{?[a-z_]+\}?[\\/]|\.\.(?:[\\/]|\s|$)", _FLAGS)
_STATEMENT = re.compile(r";|&&|\|\||\||\r?\n")

_RULES: list[tuple[re.Pattern[str], str]] = [
    # --- destroys data beyond the project ---------------------------------------------------------------
    (
        re.compile(_word(r"format-volume|clear-disk|initialize-disk|remove-partition|diskpart|mkfs(?:\.\w+)?"), _FLAGS),
        "it erases or repartitions a disk",
    ),
    (re.compile(_word("format") + r"\s+[a-z]:", _FLAGS), "it erases a disk"),
    (re.compile(_word("cipher") + r"\s+/w", _FLAGS), "it wipes free disk space"),
    (re.compile(_word("sdelete(?:64)?"), _FLAGS), "it wipes files beyond recovery"),
    (re.compile(_word("vssadmin|wbadmin") + r"\s+delete", _FLAGS), "it deletes backups or restore points"),
    (re.compile(_word("reg") + r"\s+delete", _FLAGS), "it deletes from the registry"),
    (
        re.compile(
            _word("remove-item(?:property)?|rm|ri|del") + r"[^;|\n]*\b(?:hklm|hkcu|hkcr|hku|registry::)", _FLAGS
        ),
        "it deletes from the registry",
    ),
    (re.compile(_word("bcdedit|bootrec|bootsect"), _FLAGS), "it changes how the PC starts"),
    # --- weakens the PC's security ----------------------------------------------------------------------
    (
        re.compile(_word(r"set-mppreference|add-mppreference|remove-mppreference|set-executionpolicy"), _FLAGS),
        "it changes a security setting of the PC",
    ),
    (
        re.compile(
            _word(r"set-netfirewallprofile|(?:new|set|remove|disable|enable)-netfirewallrule")
            + "|"
            + _word("netsh")
            + r"\s+(?:advfirewall|firewall)",
            _FLAGS,
        ),
        "it changes the firewall",
    ),
    (
        re.compile(
            _word(r"(?:new|set|remove|enable|disable)-localuser|(?:add|remove)-localgroupmember")
            + "|"
            + _word("net1?")
            + r"\s+(?:user|localgroup|accounts)",
            _FLAGS,
        ),
        "it changes user accounts",
    ),
    (re.compile(_word("reg") + r"\s+add\s+\"?(?:hklm|hkey_local_machine)", _FLAGS), "it changes system settings"),
    (
        re.compile(_word("takeown") + "|" + _word("icacls") + r"[^;|\n]*/(?:grant|setowner|reset)", _FLAGS),
        "it changes who may access files",
    ),
    # --- moves files to or from another machine ----------------------------------------------------------
    (
        re.compile(
            _word(
                r"invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-bitstransfer|bitsadmin|aria2c|"
                r"scp|sftp|ftp|tftp|rsync|rclone|ncat|nc|netcat|send-mailmessage"
            ),
            _FLAGS,
        ),
        "it sends or fetches files over the network",
    ),
    (re.compile(_word("certutil") + r"[^;|\n]*-urlcache", _FLAGS), "it fetches a file from the network"),
    (
        re.compile(
            r"net\.webclient|httpclient|downloadfile|downloadstring|downloaddata|uploadfile|uploadstring|uploaddata|net\.sockets",
            _FLAGS,
        ),
        "it sends or fetches files over the network",
    ),
    (
        re.compile(
            _word("git")
            + r"\s+(?:[^;|\n]*\s)?push\b|"
            + _word("gh")
            + r"\s+(?:gist\s+create|release\s+(?:create|upload)|repo\s+create)|"
            + _word("npm|pnpm|yarn")
            + r"\s+publish|"
            + _word("twine")
            + r"\s+upload|"
            + _word("docker|podman")
            + r"\s+push|"
            + _word("aws")
            + r"\s+s3\s+(?:cp|mv|sync)|"
            + _word("gsutil")
            + r"\s+(?:cp|mv|rsync)|"
            + _word("az")
            + r"\s+storage\s+\w+\s+upload",
            _FLAGS,
        ),
        "it publishes or uploads files",
    ),
    (
        re.compile(
            _word("ngrok|cloudflared|localtunnel|new-smbshare")
            + "|"
            + _word("tailscale")
            + r"\s+(?:serve|funnel|file)|"
            + _word("net1?")
            + r"\s+share|-m\s+http\.server|"
            + _word("http-server|serve"),
            _FLAGS,
        ),
        "it makes files on this PC reachable from other machines",
    ),
    # --- hides what it runs ------------------------------------------------------------------------------
    (
        re.compile(r"\s-e(?:nc|ncodedcommand|c)?\s+[a-z0-9+/=]{16,}|frombase64string", _FLAGS),
        "its real text is hidden, so it cannot be checked",
    ),
]


def refusal(command: str) -> str | None:
    """Why this command is never run, or None when it may be asked about as usual."""
    for pattern, reason in _RULES:
        if pattern.search(command):
            return reason
    for statement in _STATEMENT.split(command):
        found = _DELETE.search(statement)
        if found and _OUTSIDE.search(statement[found.end() :]):
            return "it deletes outside the project folder (use a path inside the project, or the delete tool)"
    return None


def refusal_words(reason: str) -> str:
    return f"Refused, and the user was not asked: {reason}. This rule cannot be approved away. Choose another way."
