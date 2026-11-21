import requests
import hashlib
from typing import Optional, Dict, Any, List
import config
import database

# Exact 36 live domains from VookMail (grouped as on vookmail.com)
VOOK_GROUPS = [
    {
        "name": "Most trusted domains",
        "icon": "🛡️",
        "domains": [
            "lockomail.com", "mailzena.com", "privoramail.com", "privoxmail.com",
            "safixmail.com", "secromail.com", "securemailo.com", "trustmailo.com",
            "hitexi.com", "ottxt.com"
        ]
    },
    {
        "name": "Featured domains",
        "icon": "🚀",
        "domains": [
            "inboxnuvia.com", "mailnexio.com", "mailnuvia.com", "mailquix.com",
            "mailviro.com", "mailziq.com", "niramail.com", "qorimail.com",
            "velnuvia.com", "vomailo.com", "helmetmail.com"
        ]
    },
    {
        "name": "Most searched domains",
        "icon": "🔥",
        "domains": [
            "boxentra.com", "inboxinity.com", "mailkivo.com", "mailvona.com",
            "qivomail.com", "tmallbox.com", "vexonmail.com", "zinboxa.com",
            "trkolik.com", "moiff.com"
        ]
    },
    {
        "name": "New domains",
        "icon": "🆕",
        "domains": [
            "mailentro.com", "mivomail.com", "veylax.com", "vimomail.com", "mailcogny.com"
        ]
    }
]

ALL_VOOK_DOMAINS = [d for g in VOOK_GROUPS for d in g["domains"]]

class VookMailClient:
    def __init__(self):
        self.base_url = config.VOOK_BASE_URL.rstrip('/')
        self.session = requests.Session()

    def get_api_key(self) -> str:
        db_key = database.get_setting("vook_api_key", "")
        return db_key if db_key else config.VOOK_API_KEY

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.vookmail.com/",
            "Origin": "https://www.vookmail.com"
        }
        key = self.get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _count_zero_bits(self, byte_data: bytes) -> int:
        count = 0
        for byte in byte_data:
            if byte == 0:
                count += 8
            else:
                count += 8 - byte.bit_length()
                break
        return count

    def _solve_challenge(self, challenge: str, difficulty: int = 16) -> str:
        """Solves VookMail's SHA-256 Proof-of-Work challenge in Python in milliseconds."""
        nonce = 0
        prefix = f"{challenge}:".encode('ascii')
        while True:
            digest = hashlib.sha256(prefix + str(nonce).encode('ascii')).digest()
            if self._count_zero_bits(digest) >= difficulty:
                return str(nonce)
            nonce += 1

    def get_domains_data(self) -> Dict[str, Any]:
        """Fetch domains and categories live from VookMail API."""
        url = f"{self.base_url}/domains"
        try:
            resp = self.session.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "domains" in data and len(data["domains"]) > 0:
                    return {
                        "domains": data.get("domains", ALL_VOOK_DOMAINS),
                        "groups": data.get("groups", VOOK_GROUPS)
                    }
        except Exception as e:
            print(f"[VookMailAPI] Error fetching live domains: {e}")

        return {
            "domains": ALL_VOOK_DOMAINS,
            "groups": VOOK_GROUPS
        }

    def get_domains(self) -> List[str]:
        data = self.get_domains_data()
        return data.get("domains", ALL_VOOK_DOMAINS)

    def create_mailbox(self, username: Optional[str] = None, domain: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a real temporary mailbox on VookMail.
        If an API key is configured, uses Bearer Auth.
        If no API key is set, automatically fetches and solves VookMail's live PoW challenge!
        """
        url = f"{self.base_url}/mailboxes"
        payload = {}
        if username:
            payload["username"] = username
        if domain and domain.strip() and domain.strip().lower() not in ("auto", "default"):
            payload["domain"] = domain.strip().lstrip('@')

        api_key = self.get_api_key()
        cookie_header = ""

        # If no API key, solve live challenge
        if not api_key:
            try:
                challenge_res = self.session.get(f"{self.base_url}/challenge", headers=self._headers(), timeout=10)
                if challenge_res.status_code == 200:
                    c_data = challenge_res.json()
                    c_str = c_data.get("challenge", "")
                    diff = c_data.get("difficulty", 16)
                    nonce = self._solve_challenge(c_str, diff)
                    payload["challenge"] = c_str
                    payload["nonce"] = nonce
            except Exception as e:
                print(f"[VookMailAPI] Challenge fetch error: {e}")

        try:
            resp = self.session.post(url, json=payload, headers=self._headers(), timeout=15)
            if resp.status_code in (200, 201):
                box = resp.json()
                # Capture session cookie if returned
                cookies = resp.headers.get("Set-Cookie", "")
                if not cookies and "Set-Cookie" in resp.raw.headers:
                    cookies = resp.raw.headers.get("Set-Cookie", "")
                
                # Format cookies from session
                session_cookies = self.session.cookies.get_dict()
                cookie_str = "; ".join([f"{k}={v}" for k, v in session_cookies.items()])
                box["cookie"] = cookie_str

                return {"success": True, "data": box}

            error_msg = f"HTTP {resp.status_code}"
            try:
                err_json = resp.json()
                error_msg = err_json.get("error", {}).get("message") or err_json.get("message") or str(err_json)
            except Exception:
                pass
            return {"success": False, "error": error_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_messages(self, address: str, token: Optional[str] = None, cookie: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch real live messages for a mailbox from VookMail.
        Uses session cookies and/or Bearer token for authentic access.
        """
        url = f"{self.base_url}/mailboxes/{address}/messages"
        headers = self._headers()

        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie:
            headers["Cookie"] = cookie

        try:
            resp = self.session.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                messages = data if isinstance(data, list) else data.get("messages", data.get("data", []))
                return {"success": True, "messages": messages, "expires_at": data.get("expires_at")}
            
            error_msg = f"HTTP {resp.status_code}"
            try:
                err_json = resp.json()
                error_msg = err_json.get("error", {}).get("message") or err_json.get("message") or str(err_json)
            except Exception:
                pass
            return {"success": False, "error": error_msg, "messages": []}
        except Exception as e:
            return {"success": False, "error": str(e), "messages": []}

    def get_message_detail(self, address: str, message_id: str, token: Optional[str] = None, cookie: Optional[str] = None) -> Dict[str, Any]:
        """Fetch full sanitized body of a specific message."""
        url = f"{self.base_url}/mailboxes/{address}/messages/{message_id}"
        headers = self._headers()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie:
            headers["Cookie"] = cookie

        try:
            resp = self.session.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_mailbox(self, address: str, token: Optional[str] = None, cookie: Optional[str] = None) -> bool:
        """Permanently delete a mailbox."""
        url = f"{self.base_url}/mailboxes/{address}"
        headers = self._headers()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie:
            headers["Cookie"] = cookie

        try:
            resp = self.session.delete(url, headers=headers, timeout=10)
            return resp.status_code in (200, 204)
        except Exception:
            return False
