from prometheus_client import Counter

LOGINS = Counter("identity_logins_total", "Login attempts by result", ["result"])
REGISTRATIONS = Counter("identity_registrations_total", "Accounts created", ["role"])
REFRESHES = Counter("identity_refresh_total", "Refresh token exchanges by result", ["result"])
ACCESS_REVOCATIONS = Counter(
    "identity_access_token_revocations_total",
    "Access tokens put on the revocation list",
    ["result"],
)
ABUSE_BLOCKS = Counter(
    "identity_abuse_blocks_total",
    "Register and login attempts refused by the abuse guard",
    ["action", "reason"],
)
