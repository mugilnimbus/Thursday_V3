package app.thursday.domain

/**
 * Whether answering an approval card asks for the phone's fingerprint or lock-screen credential first.
 * Denying never asks, because it cannot cause harm. Allowing asks while the check is on, which is a setting of
 * this device (on unless it was turned off).
 */
fun approvalNeedsCheck(decision: String, checkOn: Boolean): Boolean = decision != "deny" && checkOn
