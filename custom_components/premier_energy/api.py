"""Client asincron pentru portalul clienților Premier Energy (app.premierenergy.ro, Azure AD B2C + API)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import aiohttp
from yarl import URL

from .const import (
    API_BASE,
    AUTHORITY,
    B2C_POLICY,
    CLIENT_ID,
    GAS_POD_PREFIX,
    PORTAL_ORIGIN,
    REDIRECT_URI,
    SCOPE,
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


def _pkce() -> tuple[str, str]:
    """Generează (code_verifier, code_challenge S256) pentru fluxul OAuth2 code."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def parse_authorize_html(html: str) -> tuple[str, str]:
    """Extrage (csrf, tx) din pagina de autorizare B2C."""
    csrf = _RE_CSRF.search(html)
    tx = _RE_TX.search(html)
    if not csrf or not tx:
        raise PremierEnergyConnectionError("Pagina de login are alt format (csrf/tx lipsă)")
    return csrf.group(1), tx.group(1)


def code_from_location(location: str) -> str:
    """Extrage codul de autorizare din redirectul final (…/?code=…)."""
    code = parse_qs(urlparse(location).query).get("code", [""])[0]
    if not code:
        raise PremierEnergyAuthError("Redirectul final nu conține cod de autorizare")
    return code


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


def _amount(inv: dict) -> Any:
    """Suma facturii — numele câmpului poate diferi între versiuni de API."""
    for key in ("TOTAL_AMNT", "Suma", "SUMA", "amount", "suma"):
        if inv.get(key) not in (None, ""):
            return inv.get(key)
    return None


def _has_pdf(inv: dict) -> bool:
    for key in ("existaPDF", "existaPdf", "pdf", "PDF", "hasPdf"):
        if key in inv:
            return bool(inv.get(key))
    return False


def normalize(places: list[dict], invoices: list[dict]) -> dict[str, dict[str, Any]]:
    """Grupează facturile pe PoD (doar gaz; dacă nu există, toate), cele mai noi întâi."""
    all_pods = {p.get("PoD") for p in places if p.get("PoD")}
    all_pods |= {i.get("POD") for i in invoices if i.get("POD")}
    pods = {p for p in all_pods if is_gas_pod(p)} or all_pods
    address = {p.get("PoD"): p.get("Adresa") for p in places}
    result: dict[str, dict[str, Any]] = {}
    for pod in sorted(p for p in pods if p):
        items = []
        for inv in invoices:
            if inv.get("POD") != pod:
                continue
            items.append(
                {
                    "numar": inv.get("OPBEL"),
                    "emisa": (inv.get("BLDAT") or "")[:10] or None,
                    "scadenta": (inv.get("FAEDN") or "")[:10] or None,
                    "suma": _amount(inv),
                    "pdf": _has_pdf(inv),
                }
            )
        items.sort(key=lambda x: x["emisa"] or "", reverse=True)
        result[pod] = {"adresa": address.get(pod), "facturi": items}
    return result


class PremierEnergyApi:
    """Login B2C (auth-code + PKCE) + apeluri API, cu re-login automat."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._exp = 0.0

    async def async_login(self) -> None:
        """Autentificare completă; întoarce un access token pentru API."""
        verifier, challenge = _pkce()
        state = uuid.uuid4().hex
        authorize = (
            f"{AUTHORITY}/oauth2/v2.0/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={quote(REDIRECT_URI, safe='')}"
            f"&response_type=code"
            f"&scope={quote(SCOPE, safe='')}"
            f"&code_challenge={challenge}&code_challenge_method=S256"
            f"&nonce={uuid.uuid4().hex}&state={state}&prompt=login"
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
                    _LOGGER.debug("login 1/4 authorize: HTTP %s", resp.status)
                    if resp.status != 200:
                        raise PremierEnergyConnectionError(f"authorize HTTP {resp.status}")
                    _store(resp)
                    csrf, tx = parse_authorize_html(await resp.text())

                # tx conține „=” (StateProperties=…); B2C îl vrea neschimbat.
                self_asserted = URL(
                    f"{AUTHORITY}/SelfAsserted?tx={tx}&p={B2C_POLICY}",
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
                    _LOGGER.debug(
                        "login 2/4 SelfAsserted: HTTP %s non-JSON, body=%r",
                        http_status, text[:80],
                    )
                    raise PremierEnergyConnectionError(
                        f"SelfAsserted HTTP {http_status} răspuns non-JSON ({resp.headers.get('Content-Type')})"
                    ) from None
                _LOGGER.debug(
                    "login 2/4 SelfAsserted: HTTP %s, status=%s, message=%r",
                    http_status, status, message,
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
                        f"{AUTHORITY}/api/CombinedSigninAndSignup/confirmed"
                        f"?rememberMe=false&csrf_token={quote(csrf_cookie, safe='')}"
                        f"&tx={tx}&p={B2C_POLICY}",
                        encoded=True,
                    ),
                    headers={"Referer": authorize, **_cookie()},
                    allow_redirects=False,
                ) as resp:
                    location = resp.headers.get("Location", "")
                    loc_parts = urlparse(location)
                    q_keys = sorted(parse_qs(loc_parts.query))
                    err = parse_qs(loc_parts.query).get("error_description", [""])[0][:200]
                    _LOGGER.debug(
                        "login 3/4 confirmed: HTTP %s, location=%s%s, query keys=%s, error=%r",
                        resp.status, loc_parts.netloc, loc_parts.path, q_keys, err,
                    )
                    if resp.status not in (301, 302, 303) or "code=" not in location:
                        raise PremierEnergyConnectionError(
                            f"Fără cod după confirmare (HTTP {resp.status}) {err}"
                        )
                code = code_from_location(location)

                # 4/4: schimbăm codul pe un access token.
                async with s.post(
                    URL(f"{AUTHORITY}/oauth2/v2.0/token", encoded=True),
                    data={
                        "grant_type": "authorization_code",
                        "client_id": CLIENT_ID,
                        "code": code,
                        "redirect_uri": REDIRECT_URI,
                        "code_verifier": verifier,
                        "scope": SCOPE,
                    },
                    headers={"Origin": PORTAL_ORIGIN, **_cookie()},
                ) as resp:
                    token_text = await resp.text()
                    _LOGGER.debug("login 4/4 token: HTTP %s", resp.status)
                    try:
                        tok = json.loads(token_text)
                    except ValueError:
                        raise PremierEnergyConnectionError(
                            f"token HTTP {resp.status} răspuns non-JSON"
                        ) from None
                    access = tok.get("access_token")
                    if not access:
                        desc = str(tok.get("error_description", tok.get("error", "")))[:200]
                        raise PremierEnergyConnectionError(f"token fără access_token: {desc}")
                    self._token = access
                    self._exp = token_expiry(access)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PremierEnergyConnectionError(str(err)) from err

    async def _get(self, path: str, params: dict[str, str]) -> list[dict]:
        if not self._token or time.time() > self._exp - TOKEN_MARGIN:
            await self.async_login()
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {self._token}",
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
                    # Serverul poate trimite JSON cu Content-Type text/plain.
                    return json.loads(await resp.text())
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise PremierEnergyConnectionError(f"{path}: {err}") from err
        raise PremierEnergyConnectionError(path)

    async def async_get_data(self) -> dict[str, dict[str, Any]]:
        """Locuri de consum + facturi, grupate pe PoD de gaz."""
        places = await self._get("locConsum", {"cuAdresa": "true"})
        invoices = await self._get("facturi", {})
        return normalize(places, invoices)
