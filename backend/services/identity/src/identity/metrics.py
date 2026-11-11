from prometheus_client import Counter

LOGINS = Counter("identity_logins_total", "Login attempts by result", ["result"])
REGISTRATIONS = Counter("identity_registrations_total", "Accounts created", ["role"])
REFRESHES = Counter("identity_refresh_total", "Refresh token exchanges by result", ["result"])
