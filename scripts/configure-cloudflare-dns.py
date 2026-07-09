"""Configure Cloudflare DNS records for quannengyanjiu.cn.

This script adds 3 DNS records via the Cloudflare API v4:
    1. A     quannengyanjiu.cn        -> <VERCEL_IP>              (Vercel A record)
    2. CNAME www.quannengyanjiu.cn    -> cname.vercel-dns.com     (Vercel CNAME)
    3. CNAME api.quannengyanjiu.cn    -> <RAILWAY_DOMAIN>         (Railway backend)

==============================================================================
  HOW TO GET A CLOUDFLARE API TOKEN
==============================================================================
  1. Log in to https://dash.cloudflare.com/profile/api-tokens
  2. Click "Create Token" -> "Edit zone DNS" template (or custom token).
  3. Required permission:  Zone : DNS : Edit
  4. (Optional) Scope the token to the specific zone for quannengyanjiu.cn.
  5. Copy the generated token (shown only once).

  You also need the Zone ID for quannengyanjiu.cn:
     - Found on the Cloudflare dashboard overview page (right sidebar),
       or via:  curl -X GET "https://api.cloudflare.com/client/v4/zones?name=quannengyanjiu.cn" \
                -H "Authorization: Bearer <TOKEN>"
     - If you leave --zone-id / CLOUDFLARE_ZONE_ID empty, this script will
       list your zones and auto-select the one matching quannengyanjiu.cn.

==============================================================================
  HOW TO GET VERCEL_IP AND RAILWAY_DOMAIN
==============================================================================
  VERCEL_IP:
     - From Vercel dashboard -> project -> Settings -> Domains, or
     - Run:  vercel domains inspect quannengyanjiu.cn   (look for "A record")
     - Common Vercel IPs: 76.76.21.21, 66.94.108.41 (use the one Vercel shows).

  RAILWAY_DOMAIN:
     - From Railway dashboard -> your backend service -> Settings -> Networking
       -> "Public Domain" (e.g. scholarmind-backend.up.railway.app), or
     - Run:  railway status   (look for the public domain).

==============================================================================
  USAGE EXAMPLES
==============================================================================
  # 1. Using environment variables (recommended)
     export CLOUDFLARE_API_TOKEN=xxxx
     export CLOUDFLARE_ZONE_ID=yyyy        # optional
     export VERCEL_IP=76.76.21.21
     export RAILWAY_DOMAIN=scholarmind-backend.up.railway.app
     python scripts/configure-cloudflare-dns.py

  # 2. Using command-line arguments
     python scripts/configure-cloudflare-dns.py \
         --token xxxx \
         --zone-id yyyy \
         --vercel-ip 76.76.21.21 \
         --railway-domain scholarmind-backend.up.railway.app

  # 3. Mix: rely on env vars, override only what you need
     python scripts/configure-cloudflare-dns.py --vercel-ip 76.76.21.21

  # 4. Dry run (only validate + show what would happen, do not write)
     python scripts/configure-cloudflare-dns.py --dry-run

Dependencies:
     requests  (pip install requests)
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_BASE = "https://api.cloudflare.com/client/v4"
DOMAIN = "quannengyanjiu.cn"

# Records to be created/updated. The "value" fields marked with ENV markers
# will be filled from environment variables or CLI args at runtime.
RECORDS: list[dict[str, str]] = [
    {
        "type": "A",
        "name": DOMAIN,
        "content_env": "VERCEL_IP",
        "content_arg": "vercel_ip",
        "proxied": "false",
        "ttl": "1",  # 1 = automatic
        "comment": "Vercel A record",
    },
    {
        "type": "CNAME",
        "name": f"www.{DOMAIN}",
        "content": "cname.vercel-dns.com",
        "proxied": "false",
        "ttl": "1",
        "comment": "Vercel CNAME for www",
    },
    {
        "type": "CNAME",
        "name": f"api.{DOMAIN}",
        "content_env": "RAILWAY_DOMAIN",
        "content_arg": "railway_domain",
        "proxied": "false",
        "ttl": "1",
        "comment": "Railway backend CNAME",
    },
]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Cloudflare API wrappers
# ---------------------------------------------------------------------------
class CloudflareError(RuntimeError):
    """Raised when a Cloudflare API call fails."""

    def __init__(self, message: str, status_code: int | None = None,
                 errors: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors


def _raise_for_cloudflare_error(resp: requests.Response, action: str) -> None:
    """Inspect a Cloudflare response and raise a helpful error on failure."""
    if resp.ok:
        return

    status = resp.status_code
    try:
        body = resp.json()
        errors_list = body.get("errors") or []
        messages = body.get("messages") or []
    except ValueError:
        errors_list = []
        messages = []

    # Build a readable error description.
    details = []
    for err in errors_list:
        code = err.get("code")
        msg = err.get("message")
        details.append(f"code={code} message={msg}")
    msg_text = "; ".join(details) if details else (resp.text or "no body")

    # Distinguish common failure modes for clearer user feedback.
    if status in (401, 403):
        hint = (
            "Authentication failed. Check that CLOUDFLARE_API_TOKEN is valid "
            "and has Zone:DNS:Edit permission on the target zone."
        )
    elif status == 404:
        hint = "Resource not found. Check the zone id and record name."
    elif status == 429:
        hint = "Rate limited. Wait a moment and retry."
    else:
        hint = "Cloudflare API call failed."

    raise CloudflareError(
        f"{action} failed (HTTP {status}): {msg_text}. {hint}",
        status_code=status,
        errors=errors_list + messages,
    )


def cf_request(method: str, path: str, token: str,
               json: dict | None = None) -> dict:
    """Make an authenticated request to the Cloudflare API and return JSON."""
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, json=json, timeout=30)
    _raise_for_cloudflare_error(resp, f"{method} {path}")
    body = resp.json()
    if not body.get("success", True):
        raise CloudflareError(
            f"Cloudflare returned success=false for {method} {path}: "
            f"{body.get('errors')}",
            status_code=resp.status_code,
            errors=body.get("errors"),
        )
    return body


def validate_token(token: str) -> dict:
    """Validate the API token by calling /user/tokens/verify."""
    # Note: this endpoint uses the same Authorization header.
    resp = requests.get(
        f"{API_BASE}/user/tokens/verify",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if not resp.ok:
        _raise_for_cloudflare_error(resp, "token verification")
    body = resp.json()
    return body.get("result", {})


def list_zones(token: str, name: str | None = None) -> list[dict]:
    """List zones accessible by the token, optionally filtered by name."""
    params = {}
    if name:
        params["name"] = name
    body = cf_request("GET", "/zones", token)
    # cf_request returns the parsed body; the zones endpoint also accepts
    # query params via a separate call helper below, so re-issue with params.
    # (Kept simple here: list all zones and filter in Python.)
    return body.get("result", []) or []


def find_zone_for_domain(token: str, domain: str) -> dict | None:
    """Find the zone that matches the given apex domain."""
    body = cf_request("GET", f"/zones?name={domain}", token)
    zones = body.get("result", []) or []
    if not zones:
        # Fallback: list all zones and match by suffix.
        all_zones = list_zones(token)
        zones = [z for z in all_zones if z.get("name") == domain]
    return zones[0] if zones else None


def list_dns_records(token: str, zone_id: str,
                     name: str | None = None,
                     rtype: str | None = None) -> list[dict]:
    """List DNS records for a zone, optionally filtered by name/type."""
    path = f"/zones/{zone_id}/dns_records"
    params: list[str] = []
    if name:
        params.append(f"name={name}")
    if rtype:
        params.append(f"type={rtype}")
    if params:
        path += "?" + "&".join(params)
    body = cf_request("GET", path, token)
    return body.get("result", []) or []


def create_dns_record(token: str, zone_id: str, payload: dict) -> dict:
    """Create a new DNS record."""
    body = cf_request("POST", f"/zones/{zone_id}/dns_records", token,
                      json=payload)
    return body.get("result", {})


def update_dns_record(token: str, zone_id: str, record_id: str,
                      payload: dict) -> dict:
    """Update an existing DNS record (PUT replaces it)."""
    body = cf_request(
        "PUT",
        f"/zones/{zone_id}/dns_records/{record_id}",
        token,
        json=payload,
    )
    return body.get("result", {})


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------
def upsert_record(token: str, zone_id: str, record: dict[str, str]) -> str:
    """Create or update a DNS record. Returns the record id.

    `record` must contain: type, name, content, ttl, proxied, comment.
    """
    rtype = record["type"]
    name = record["name"]
    content = record["content"]

    existing = list_dns_records(token, zone_id, name=name, rtype=rtype)
    # Cloudflare matches case-insensitively for name; ensure exact match.
    exact = [r for r in existing if r.get("name", "").lower() == name.lower()]

    payload = {
        "type": rtype,
        "name": name,
        "content": content,
        "ttl": int(record.get("ttl", 1)),
        "proxied": str(record.get("proxied", "false")).lower() == "true",
        "comment": record.get("comment", ""),
    }

    if not exact:
        info(f"Adding {rtype} record: {name} -> {content}")
        created = create_dns_record(token, zone_id, payload)
        rid = created.get("id", "")
        ok(f"{rtype} record added (record_id={rid})")
        return rid

    # Exactly one (or more) existing record matches -> update the first.
    target = exact[0]
    rid = target.get("id", "")
    if target.get("content", "").rstrip(".") == content.rstrip("."):
        ok(f"{rtype} record already correct: {name} -> {content} "
            f"(record_id={rid})")
        return rid

    info(f"Updating existing {rtype} record: {name} "
         f"{target.get('content')} -> {content}")
    updated = update_dns_record(token, zone_id, rid, payload)
    ok(f"{rtype} record updated (record_id={rid})")
    return rid


def verify_dns_resolution(name: str, expected: str, rtype: str) -> None:
    """Best-effort DNS verification via socket. Never raises."""
    try:
        if rtype == "A":
            resolved = socket.gethostbyname(name)
            match = resolved == expected
        else:
            # CNAME resolution: gethostbyname returns the A record the CNAME
            # points to, so we just confirm it resolves at all.
            try:
                resolved = socket.gethostbyname(name)
            except socket.gaierror:
                resolved = None
            match = resolved is not None
        if match:
            ok(f"DNS verification OK: {name} resolves"
                + (f" to {resolved}" if resolved else ""))
        else:
            warn(f"DNS verification mismatch for {name}: "
                 f"expected {expected}, got {resolved}. "
                 "DNS propagation can take a few minutes; retry later.")
    except socket.gaierror as e:
        warn(f"DNS verification skipped for {name}: {e}. "
             "DNS propagation can take a few minutes; retry later.")
    except Exception as e:  # noqa: BLE001
        warn(f"DNS verification failed for {name}: {e}")


# ---------------------------------------------------------------------------
# Argument parsing & main
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure Cloudflare DNS records for "
                    f"{DOMAIN} (Vercel + Railway).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        help="Cloudflare API token with Zone:DNS:Edit permission. "
             "Defaults to env CLOUDFLARE_API_TOKEN.",
    )
    parser.add_argument(
        "--zone-id",
        default=os.environ.get("CLOUDFLARE_ZONE_ID", ""),
        help="Cloudflare zone id for the apex domain. "
             "Defaults to env CLOUDFLARE_ZONE_ID. "
             "If empty, the script lists zones and auto-selects.",
    )
    parser.add_argument(
        "--vercel-ip",
        default=os.environ.get("VERCEL_IP", ""),
        help="Vercel IP address for the A record on the apex domain. "
             "Defaults to env VERCEL_IP.",
    )
    parser.add_argument(
        "--railway-domain",
        default=os.environ.get("RAILWAY_DOMAIN", ""),
        help="Railway public domain (e.g. xxx.up.railway.app) for the "
             "api.<domain> CNAME. Defaults to env RAILWAY_DOMAIN.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show planned actions without writing.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-run DNS resolution verification step.",
    )
    return parser


def resolve_record_values(args: argparse.Namespace) -> list[dict[str, str]]:
    """Fill in record content from CLI args / env vars and validate."""
    filled: list[dict[str, str]] = []
    for rec in RECORDS:
        rec = dict(rec)
        if "content" not in rec:
            # Pull from CLI arg / env var.
            arg_name = rec.get("content_arg", "")
            env_name = rec.get("content_env", "")
            value = getattr(args, arg_name, "") if arg_name else ""
            if not value and env_name:
                value = os.environ.get(env_name, "")
            if not value:
                raise SystemExit(
                    f"Missing value for {rec['type']} record "
                    f"{rec['name']}. Provide --{arg_name.replace('_', '-')} "
                    f"or set env {env_name}."
                )
            rec["content"] = value
        filled.append(rec)
    return filled


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.token:
        error("CLOUDFLARE_API_TOKEN is required. Generate one at "
              "https://dash.cloudflare.com/profile/api-tokens "
              "(Zone:DNS:Edit permission).")
        return 2

    # 1. Validate token.
    try:
        verify_result = validate_token(args.token)
    except CloudflareError as e:
        error(str(e))
        return 3
    account = verify_result.get("id", "unknown")
    status = verify_result.get("status", "unknown")
    if status and status != "active":
        error(f"Token status is '{status}', expected 'active'. "
               "Generate a new token.")
        return 3
    info(f"Cloudflare API token validated (token id={account})")

    # 2. Resolve zone id (or auto-detect).
    zone_id = (args.zone_id or "").strip()
    if zone_id:
        info(f"Using provided zone_id={zone_id}")
    else:
        info(f"No zone id provided; querying Cloudflare for {DOMAIN}...")
        try:
            zone = find_zone_for_domain(args.token, DOMAIN)
        except CloudflareError as e:
            error(str(e))
            return 4
        if not zone:
            error(f"No Cloudflare zone found for {DOMAIN}. "
                  "Add the domain to your Cloudflare account first, "
                  "or pass --zone-id explicitly.")
            return 4
        zone_id = zone.get("id", "")
        zone_name = zone.get("name", DOMAIN)
        info(f"Found zone for {zone_name} (zone_id={zone_id})")
        if zone_name != DOMAIN:
            warn(f"Zone name '{zone_name}' does not exactly match "
                 f"'{DOMAIN}'. Proceeding anyway.")

    # 3. Resolve record content values.
    records = resolve_record_values(args)

    # 4. Dry-run preview.
    if args.dry_run:
        print()
        print("Dry-run plan (no changes will be made):")
        for r in records:
            print(f"  - {r['type']:5s} {r['name']:30s} -> {r['content']}")
        return 0

    # 5. Upsert each record.
    print()
    success_count = 0
    for rec in records:
        try:
            upsert_record(args.token, zone_id, rec)
            success_count += 1
        except CloudflareError as e:
            error(f"Failed to configure {rec['type']} record "
                  f"{rec['name']}: {e}")
        except requests.RequestException as e:
            error(f"Network error configuring {rec['type']} record "
                  f"{rec['name']}: {e}")

    # 6. Summary.
    print()
    if success_count == len(records):
        info(f"All {len(records)} DNS records configured successfully")
    else:
        warn(f"{success_count}/{len(records)} records configured; "
             "see errors above.")

    # 7. Best-effort DNS verification.
    if not args.no_verify and success_count == len(records):
        print()
        info("Verifying DNS resolution (may take a few minutes to propagate)...")
        for rec in records:
            verify_dns_resolution(rec["name"], rec["content"], rec["type"])

    return 0 if success_count == len(records) else 1


if __name__ == "__main__":
    sys.exit(main())
