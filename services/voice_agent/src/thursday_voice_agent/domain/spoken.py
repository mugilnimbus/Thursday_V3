"""Spoken approval answers, recognised by code, never by the model.

An answer is recognised only while an approval is pending in that chat and only when the
whole message is one of these phrases (case, punctuation, and extra spaces ignored).
Anything else goes to the conversation as usual, so a sentence that merely contains
"yes" never approves anything.
"""

import re

from thursday_contracts.approvals import ApprovalDecision

_ALLOW_ONCE = {
    "yes",
    "yeah",
    "yep",
    "allow",
    "allow it",
    "allow once",
    "approve",
    "approved",
    "ok",
    "okay",
    "go ahead",
    "do it",
    "yes allow",
    "yes do it",
    "yes go ahead",
}
_ALLOW_ALWAYS = {"allow always", "always allow", "always", "yes always", "allow always in this chat"}
_DENY = {"no", "nope", "deny", "denied", "don't", "do not", "reject", "no don't", "don't do it", "do not do it"}


def normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def spoken_approval(text: str) -> ApprovalDecision | None:
    phrase = normalise(text)
    if phrase in _ALLOW_ALWAYS:
        return ApprovalDecision.ALLOW_ALWAYS
    if phrase in _ALLOW_ONCE:
        return ApprovalDecision.ALLOW_ONCE
    if phrase in _DENY:
        return ApprovalDecision.DENY
    return None
