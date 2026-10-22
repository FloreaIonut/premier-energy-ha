"""Client asincron pentru portalul clienților Premier Energy (Azure AD B2C + API)."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import aiohttp
from yarl import URL

from .const import (
    API_BASE,
    B2C_BASE,
    B2C_POLICY,
    B2C_POLICY_AUTHORIZE,
    CLIENT_ID,
    GAS_POD_PREFIX,
    PORTAL_ORIGIN,
    REDIRECT_URI,
    TOKEN_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
_RE_CSRF = re.compile(r'"csrf"\s*:\s*"([^"]+)"')
_RE_TX = re.compile(r'"transId"\s*:\s*"(StateProperties=[^"]+)"')
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class PremierEnergyError(Exception):
    """Eroare generală."""


class PremierEnergyConnectionError(PremierEnergyError):
    """Portalul nu răspunde sau răspuns neașteptat."""


class PremierEnergyAuthError(PremierEnergyError):
    """Email sau parolă greșite."""


def parse_authorize_html(html: str) -> tuple[str, str]:
    """Extrage (csrf, tx) din pagina de autorizare B2C."""
    csrf = _RE_CSRF.search(html)
    tx = _RE_TX.search(html)
    if not csrf or not tx:
        raise PremierEnergyConnectionError("Pagina de login are alt format (csrf/tx lipsă)")
    return csrf.group(1), tx.group(1)


def token_from_location(location: str) -> str:
    """Extrage id_token din redirectul final (…/#id_token=…)."""
    fragment = urlparse(location).fragment
    token = parse_qs(fragment).get("id_token", [""])[0]
    if not token:
        raise PremierEnergyAuthError("Redirectul final nu conține id_token")
    return token


def token_expiry(token: str) -> float:
    """Momentul expirării (epoch) din claim-ul exp al JWT; implicit 55 min."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, ValueError, KeyError):
        return time.time() + 3300


def is_gas_pod(pod: str | None) -> bool:
    """PoD-urile de gaz încep cu DGS."""
    return bool(pod) and pod.upper().startswith(GAS_POD_PREFIX)


def normalize(places: list[dict], invoices: list[dict]) -> dict[str, dict[str, Any]]:
    """Grupează facturile pe PoD (doar gaz; dacă nu există, toate), cele mai noi întâi."""
    all_pods = {p.get("PoD") for p in places if p.get("PoD")}
    all_pods |= {i.get("POD") for i in invoices if i.get("POD")}
    pods = {p for p in all_pods if is_gas_pod(p)} or all_pods
    address = {p.get("PoD"): p.get("Adresa") for p in places}
    result: dict[str, dict[str, Any]] = {}
    for pod in sorted(pods):
        items = []
        for inv in invoices:
            if inv.get("POD") != pod:
                continue
            items.append(
                {
                    "numar": inv.get("OPBEL"),
                    "emisa": (inv.get("BLDAT") or "")[:10] or None,
                    "scadenta": (inv.get("FAEDN") or "")[:10] or None,
                    "suma": inv.get("TOTAL_AMNT"),
                    "pdf": bool(inv.get("existaPDF")),
                }
            )
        items.sort(key=lambda x: x["emisa"] or "", reverse=True)
        result[pod] = {"adresa": address.get(pod), "facturi": items}
    return result


class PremierEnergyApi:
    """Login B2C + apeluri API, cu re-login automat."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._exp = 0.0

    async def async_login(self) -> None:
        """Autentificare completă (cookie-uri B2C doar într-o sesiune temporară)."""
        authorize = (
            f"{B2C_BASE}/oauth2/v2.0/authorize?p={B2C_POLICY_AUTHORIZE}"
            f"&redirect_uri={quote(REDIRECT_URI, safe='')}&client_id={CLIENT_ID}"
            f"&nonce={uuid.uuid4().hex}&scope=openid&response_type=id_token&prompt=login"
        )
        headers = {"User-Agent": _UA}
        try:
            # aiohttp pune ghilimele în jurul valorilor de cookie cu „=”, „/” (csrf, trans, cache)
            # și B2C respinge cererea (400 „Bad Request”). Gestionăm cookie-urile manual, brut.
            jar: dict[str, str] = {}

            def _cookie() -> dict[str, str]:
                return {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())}

            def _store(resp: aiohttp.ClientResponse) -> None:
                for name, morsel in resp.cookies.items():
                    jar[name] = morsel.value

            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.DummyCookieJar(), timeout=_TIMEOUT, headers=headers
            ) as s:
                async with s.get(authorize) as resp:
                    _LOGGER.debug("login 1/3 authorize: HTTP %s", resp.status)
                    if resp.status != 200:
                        raise PremierEnergyConnectionError(f"authorize HTTP {resp.status}")
                    _store(resp)
                    csrf, tx = parse_authorize_html(await resp.text())

                # tx conține „=” (StateProperties=…); B2C îl vrea neschimbat, ca în JS-ul paginii.
                # params={...} l-ar codifica %3D și B2C răspunde 400 „Bad Request” (text/html).
                self_asserted = URL(
                    f"{B2C_BASE}/{B2C_POLICY}/SelfAsserted?tx={tx}&p={B2C_POLICY}",
                    encoded=True,
                )
                async with s.post(
                    self_asserted,
                    data={
                        "request_type": "RESPONSE",
                        "signInName": self._email,
                        "password": self._password,
                    },
                    headers={
                        "X-CSRF-TOKEN": csrf,
                        "X-Requested-With": "XMLHttpRequest",
                        "Origin": "https://login.premierenergy.ro",
                        "Referer": authorize,
                        **_cookie(),
                    },
                ) as resp:
                    _store(resp)
                    text = await resp.text()
                http_status = resp.status
                message = ""
                try:
                    body = json.loads(text)
                    status = str(body.get("status"))
                    message = str(body.get("message", ""))[:200]  # mesaj B2C, fără secrete
                except (ValueError, AttributeError):
                    _LOGGER.debug("login 2/3 SelfAsserted: HTTP %s non-JSON, body=%r", http_status, text[:80])
                    # Nu e JSON B2C (ex. „Bad Request” text/html) => cerere respinsă, nu parolă greșită.
                    raise PremierEnergyConnectionError(
                        f"SelfAsserted HTTP {http_status} răspuns non-JSON ({resp.headers.get('Content-Type')})"
                    ) from None
                _LOGGER.debug(
                    "login 2/3 SelfAsserted: HTTP %s, status=%s, message=%r, content-type=%s",
                    http_status, status, message, resp.headers.get("Content-Type"),
                )
                if status in ("400", "401"):
                    raise PremierEnergyAuthError(f"SelfAsserted {status}: {message}")
                if status != "200" or http_status != 200:
                    raise PremierEnergyConnectionError(
                        f"SelfAsserted HTTP {http_status} status {status}: {message}"
                    )

                # B2C poate roti cookie-ul csrf; îl preferăm pe cel curent.
                csrf_cookie = jar.get("x-ms-cpim-csrf", csrf)
                async with s.get(
                    URL(
                        f"{B2C_BASE}/{B2C_POLICY}/api/CombinedSigninAndSignup/confirmed"
                        f"?rememberMe=false&csrf_token={quote(csrf_cookie, safe='')}"
                        f"&tx={tx}&p={B2C_POLICY}",
                        encoded=True,
                    ),
                    headers={"Referer": authorize, **_cookie()},
                    allow_redirects=False,
                ) as resp:
                    location = resp.headers.get("Location", "")
                    # Fără fragmentul cu token; păstrăm doar host/cale și codurile de eroare.
                    loc_parts = urlparse(location)
                    frag_keys = sorted(parse_qs(loc_parts.fragment))
                    err = parse_qs(loc_parts.fragment).get("error_description", [""])[0][:200]
                    _LOGGER.debug(
                        "login 3/3 confirmed: HTTP %s, location=%s%s, fragment keys=%s, error=%r",
                        resp.status, loc_parts.netloc, loc_parts.path, frag_keys, err,
                    )
                    if resp.status not in (301, 302, 303) or "id_token" not in location:
                        # Nu e neapărat parolă greșită (ex.: pagină intermediară, T&C, MFA).
                        raise PremierEnergyConnectionError(
                            f"Fără id_token după confirmare (HTTP {resp.status}) {err}"
                        )
                self._token = token_from_location(location)
                self._exp = token_expiry(self._token)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PremierEnergyConnectionError(str(err)) from err

    async def _get(self, path: str, params: dict[str, str]) -> list[dict]:
        if not self._token or time.time() > self._exp - TOKEN_MARGIN:
            await self.async_login()
        for attempt in (1, 2):
            headers = {
                "premier-auth": f"Bearer {self._token}",
                "x-pe-request-id": str(uuid.uuid4()),
                "Origin": PORTAL_ORIGIN,
                "Accept": "application/json, text/plain, */*",
                "User-Agent": _UA,
            }
            try:
                async with self._session.get(
                    f"{API_BASE}/{path}", params=params, headers=headers, timeout=_TIMEOUT
                ) as resp:
                    if resp.status in (401, 403) and attempt == 1:
                        await self.async_login()
                        continue
                    if resp.status in (401, 403):
                        raise PremierEnergyAuthError("Token respins de API")
                    if resp.status != 200:
                        raise PremierEnergyConnectionError(f"{path} HTTP {resp.status}")
                    # Serverul trimite JSON cu Content-Type text/plain.
                    return json.loads(await resp.text())
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise PremierEnergyConnectionError(f"{path}: {err}") from err
        raise PremierEnergyConnectionError(path)

    async def async_get_data(self) -> dict[str, dict[str, Any]]:
        """Locuri de consum + facturi, grupate pe PoD de gaz."""
        places = await self._get("locConsum", {"cuAdresa": "true"})
        invoices = await self._get("facturi", {"Versiunea": "1"})
        return normalize(places, invoices)
