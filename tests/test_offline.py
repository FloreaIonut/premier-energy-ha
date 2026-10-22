"""Test offline: python3 tests/test_offline.py [authorize.html] [facturi.json] [locConsum.json]

Fără argumente rulează pe date sintetice. Cu fișiere salvate (pagina authorize, răspunsurile
API) verifică parserele pe date reale. Nu face login și nu conține date personale.
"""
import base64, importlib.util, json, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "custom_components" / "premier_energy"
# Încărcăm api.py fără HA: înlocuim importul relativ de const.
import types
pkg = types.ModuleType("pe"); pkg.__path__ = [str(root)]; sys.modules["pe"] = pkg
for name in ("const", "api"):
    spec = importlib.util.spec_from_file_location(f"pe.{name}", root / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"pe.{name}"] = mod
    spec.loader.exec_module(mod)
api = sys.modules["pe.api"]

# 1. Regexuri login
html = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else (
    'var SETTINGS = {"csrf":"AbC123==","transId":"StateProperties=eyJUSUQiOiJ4In0","api":"CombinedSigninAndSignup"};')
csrf, tx = api.parse_authorize_html(html)
assert csrf and tx.startswith("StateProperties=eyJ"), (csrf[:10], tx[:25])
print("csrf len", len(csrf), "| tx ok")

# 2. Token din redirect + expirare
payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
tok = f"aaa.{payload}.sig"
assert api.token_from_location(f"https://my.premierenergy.ro/#id_token={tok}") == tok
assert abs(api.token_expiry(tok) - time.time() - 3600) < 5
try:
    api.token_from_location("https://my.premierenergy.ro/#error=x"); raise SystemExit("fail")
except api.PremierEnergyAuthError:
    pass
print("token ok")

# 3. Facturi
if len(sys.argv) > 3:
    inv = json.loads(Path(sys.argv[2]).read_text()); places = json.loads(Path(sys.argv[3]).read_text())
else:
    inv = [{"OPBEL": "1", "BLDAT": "2026-09-15T00:00:00.000Z", "FAEDN": "2026-10-15T00:00:00.000Z", "TOTAL_AMNT": 50.00, "POD": "DGSXX1", "existaPDF": True},
           {"OPBEL": "2", "BLDAT": "2026-01-13T00:00:00.000Z", "FAEDN": "2026-02-12T00:00:00.000Z", "TOTAL_AMNT": -10.00, "POD": "DGSXX1", "existaPDF": True},
           {"OPBEL": "3", "BLDAT": "2026-10-01T00:00:00.000Z", "FAEDN": "2026-11-01T00:00:00.000Z", "TOTAL_AMNT": 5, "POD": "DEE001", "existaPDF": False}]
    places = [{"PoD": "DGSXX1", "Adresa": "Str. Test 1"}, {"PoD": "DEE001", "Adresa": "x"}]
data = api.normalize(places, inv)
for pod, d in data.items():
    f = d["facturi"]
    assert all(f[i]["emisa"] >= f[i + 1]["emisa"] for i in range(len(f) - 1))
    print(pod, "facturi:", len(f), "ultima:", f[0]["numar"], f[0]["emisa"], f[0]["scadenta"], f[0]["suma"])
assert all(api.is_gas_pod(p) for p in data)
print("OK")
