import json
import os
from http.cookies import SimpleCookie
from http.client import HTTPMessage
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("PLATEOS_VERIFY_BASE_URL", "http://verify-api:8000")


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, str] | None = None,
    cookie: str | None = None,
) -> tuple[int, HTTPMessage]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if cookie is not None:
        headers["Cookie"] = cookie
    req = Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as response:  # noqa: S310 - fixed internal URL
            response.read()
            return response.status, response.headers
    except HTTPError as exc:
        exc.read()
        if exc.headers is None:
            raise SystemExit("Internal verification response had no headers") from exc
        return exc.code, exc.headers


if request("/api/health")[0] != 200 or request("/api/ready")[0] != 200:
    raise SystemExit("Restored API is not healthy and ready")
if request("/api/profile")[0] != 401:
    raise SystemExit("Restored API accepted an unauthenticated request")

password = Path("/run/secrets/plateos_app_password").read_text(encoding="utf-8").strip()
status, headers = request(
    "/api/auth/login", method="POST", payload={"password": password}
)
if status != 200:
    raise SystemExit("Restore-only login failed")

cookies = SimpleCookie()
set_cookie = headers.get("Set-Cookie", "")
cookie_attributes = set_cookie.lower()
if not all(
    attribute in cookie_attributes
    for attribute in ("httponly", "samesite=strict", "secure")
):
    raise SystemExit("Login cookie is missing required security attributes")
cookies.load(set_cookie)
session = cookies.get("plateos_session")
if session is None:
    raise SystemExit("Restore-only login did not issue a session")
cookie_header = f"plateos_session={session.value}"

if request("/api/profile", cookie=cookie_header)[0] != 200:
    raise SystemExit("Authenticated profile read failed")
if request("/api/daily-summary", cookie=cookie_header)[0] != 200:
    raise SystemExit("Authenticated restored-data query failed")

print("PlateOS API, cookie security, authentication, and representative reads passed")
