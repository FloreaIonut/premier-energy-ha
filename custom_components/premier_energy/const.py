"""Constante pentru integrarea Premier Energy."""

from datetime import timedelta

DOMAIN = "premier_energy"

B2C_BASE = "https://login.premierenergy.ro/login.premierenergy.ro"
B2C_POLICY = "B2C_1A_signup_signin"
B2C_POLICY_AUTHORIZE = "B2C_1A_SIGNUP_SIGNIN"
CLIENT_ID = "304aaac1-c88a-4775-be6b-ac23ce30cab5"
REDIRECT_URI = "https://my.premierenergy.ro"
PORTAL_ORIGIN = "https://my.premierenergy.ro"
API_BASE = "https://peremierenergy-portalclient.azurewebsites.net/api"

GAS_POD_PREFIX = "DGS"
MAX_INVOICES_ATTR = 12
SCAN_INTERVAL = timedelta(hours=6)
# Tokenul id_token e valabil 1 h; îl reînnoim cu atâtea secunde înainte de expirare.
TOKEN_MARGIN = 300
