"""Constante pentru integrarea Premier Energy."""

from datetime import timedelta

DOMAIN = "premier_energy"

# Portalul nou: app.premierenergy.ro — Azure AD B2C (MSAL), policy SIGNUP_SIGNIN.
# Valori citite din configul MSAL al portalului (noiembrie 2026).
B2C_BASE = "https://login.premierenergy.ro/premierenergyrob2c.onmicrosoft.com"
B2C_POLICY = "B2C_1A_SIGNUP_SIGNIN"
AUTHORITY = f"{B2C_BASE}/{B2C_POLICY}"
CLIENT_ID = "5dc97de8-713e-431b-8d05-4319c180377a"
# Scope-ul API (access token); API-ul NU acceptă id_token.
API_SCOPE = "https://login.premierenergy.ro/4fea07ee-cea1-441e-a2e3-382276f2f19e/access"
SCOPE = f"openid offline_access {API_SCOPE}"
REDIRECT_URI = "https://app.premierenergy.ro/"
PORTAL_ORIGIN = "https://app.premierenergy.ro"
API_BASE = "https://app.premierenergy.ro/api"

GAS_POD_PREFIX = "DGS"
MAX_INVOICES_ATTR = 12
SCAN_INTERVAL = timedelta(hours=6)
# Access token-ul e valabil ~1 h; îl reînnoim cu atâtea secunde înainte de expirare.
TOKEN_MARGIN = 300
