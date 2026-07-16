#!/usr/bin/env python3
"""
Awarizon Testnet Auto-Farmer v2
- SIWE auth (nonce → sign → verify) with auto re-auth on 401 / JWT expiry
- Node activation (+500 pts)
- Daily check-in (+20 pts + streak)
- Social connect (+200 pts each)
- Multi-wallet batch farming
- Exponential backoff on 429

Usage:
  python3 awarizon_bot.py --action status
  python3 awarizon_bot.py --action activate
  python3 awarizon_bot.py --action checkin
  python3 awarizon_bot.py --action social --platform TWITTER --username yourhandle
  python3 awarizon_bot.py --action auto
  python3 awarizon_bot.py --action auto --wallets-dir ~/.evm-wallets
  python3 awarizon_bot.py --action checkin --wallets-dir ~/.evm-wallets
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from glob import glob
from typing import Any, Optional

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

# ─── Config ──────────────────────────────────────────────────────────
API_BASE = "https://api.awarizon.com/api/v1"
DEFAULT_WALLET = os.environ.get("AWARIZON_WALLET", "wallet.json")
TOKEN_DIR = os.path.expanduser("~/.awarizon/tokens")
DEFAULT_REFERRAL = os.environ.get("AWARIZON_REFERRAL", "")

os.makedirs(TOKEN_DIR, exist_ok=True)

# Social defaults (optional, used by auto if not already connected)
DEFAULT_SOCIALS = {
    # "TWITTER": "yourhandle",
    # "TELEGRAM": "yourname",
    # "DISCORD": "yourname",
}


# ─── Wallet helpers ──────────────────────────────────────────────────
def load_wallet(path: str) -> tuple[str, str]:
    """Load EVM private key from a file.

    Supported formats:
      - JSON with {"privateKey": "0x...", ...}  (.json)
      - Plain text: one hex key per line         (.txt / .key)
      - First line is always used (single-wallet mode)
    Returns (checksummed_address, 0x-prefixed_private_key).
    """
    with open(path) as f:
        raw = f.read().strip()

    pk: str | None = None

    # JSON format
    if path.endswith(".json"):
        data = json.loads(raw)
        pk = data.get("privateKey") or data.get("private_key") or data.get("key")
        if not pk:
            raise ValueError(f"No privateKey field found in {path}")
    else:
        # Plain text: grab first non-empty, non-comment line
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pk = line
            break

    if not pk:
        raise ValueError(f"No private key found in {path}")
    if not pk.startswith("0x"):
        pk = "0x" + pk

    acct = Account.from_key(pk)
    return acct.address, pk


def load_wallets_from_dir(dir_path: str) -> list[tuple[str, str]]:
    """Load all wallets from a directory.

    Supports:
      - *.json files  (single JSON per file)
      - pk.txt         (one private key per line, multi-wallet)
      - *.txt / *.key  (single key per file)
    Returns list of (address, pk).
    """
    results: list[tuple[str, str]] = []
    base = os.path.expanduser(dir_path)
    if not os.path.isdir(base):
        raise FileNotFoundError(f"Not a directory: {base}")

    # 1. pk.txt — multi-key file
    pk_file = os.path.join(base, "pk.txt")
    if os.path.isfile(pk_file):
        with open(pk_file) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                pk = line if line.startswith("0x") else "0x" + line
                try:
                    acct = Account.from_key(pk)
                    results.append((acct.address, pk))
                except Exception as e:
                    print(f"  ⚠️  Skip pk.txt line {lineno}: {e}")

    # 2. *.json files
    for path in sorted(glob(os.path.join(base, "*.json"))):
        try:
            results.append(load_wallet(path))
        except Exception as e:
            print(f"  ⚠️  Skip {os.path.basename(path)}: {e}")

    # 3. Other *.txt / *.key (single-key files, skip pk.txt already loaded)
    for ext in ("*.txt", "*.key"):
        for path in sorted(glob(os.path.join(base, ext))):
            if os.path.basename(path) == "pk.txt":
                continue
            try:
                results.append(load_wallet(path))
            except Exception as e:
                print(f"  ⚠️  Skip {os.path.basename(path)}: {e}")

    if not results:
        raise FileNotFoundError(f"No wallets found in {dir_path}")
    return results



# ─── API Client ──────────────────────────────────────────────────────
class AwarizonClient:
    def __init__(self, wallet_address: str, private_key: str, referral_code: str = ""):
        self.wallet = wallet_address
        self.pk = private_key
        self.referral_code = referral_code or DEFAULT_REFERRAL
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://testnet.awarizon.com/",
            "Origin": "https://testnet.awarizon.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        })
        self.token: Optional[str] = self._load_token()

    # ── token persistence ────────────────────────────────────────────
    def _token_path(self) -> str:
        return os.path.join(TOKEN_DIR, f"{self.wallet.lower()}.json")

    def _load_token(self) -> Optional[str]:
        try:
            with open(self._token_path()) as f:
                data = json.load(f)
            token = data.get("token")
            expires_at = data.get("expires_at", 0)
            if token and expires_at > time.time():
                return token
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            pass
        return None

    def _save_token(self, token: str, expires_in: Optional[int] = None) -> None:
        # Prefer real JWT exp; fallback to 900s (HAR-confirmed TTL)
        if expires_in is None:
            expires_in = self._jwt_ttl(token) or 900
        expires_at = time.time() + max(60, expires_in - 60)  # 60s buffer
        path = self._token_path()
        with open(path, "w") as f:
            json.dump({"token": token, "expires_at": expires_at}, f)
        os.chmod(path, 0o600)
        self.token = token

    @staticmethod
    def _jwt_ttl(token: str) -> Optional[int]:
        """Return seconds until JWT exp, or None if unparsable."""
        try:
            payload_b64 = token.split(".")[1]
            # pad base64url
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = int(payload.get("exp", 0))
            iat = int(payload.get("iat", 0))
            if exp and iat:
                return max(0, exp - iat)
            if exp:
                return max(0, exp - int(time.time()))
        except Exception:
            return None
        return None

    @staticmethod
    def _jwt_expired(token: str) -> bool:
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = int(payload.get("exp", 0))
            return exp <= int(time.time()) + 30  # 30s early
        except Exception:
            return True

    # ── crypto ───────────────────────────────────────────────────────
    def _sign_message(self, message: str) -> str:
        """EIP-191 personal_sign. Returns 0x-prefixed hex signature."""
        acct = Account.from_key(self.pk)
        signed = acct.sign_message(encode_defunct(text=message))
        sig = signed.signature.hex()
        return sig if sig.startswith("0x") else "0x" + sig

    # ── HTTP layer ───────────────────────────────────────────────────
    def _ensure_auth(self) -> None:
        if not self.token or self._jwt_expired(self.token):
            ok = self.authenticate()
            if not ok:
                raise RuntimeError("Authentication failed")

    def _api(
        self,
        method: str,
        path: str,
        json_data: Any = None,
        auth: bool = True,
        _retry_auth: bool = True,
        _attempt: int = 0,
    ) -> dict:
        url = f"{API_BASE}{path}"
        headers: dict[str, str] = {}
        if auth:
            self._ensure_auth()
            headers["Authorization"] = f"Bearer {self.token}"
        if json_data is not None:
            headers["Content-Type"] = "application/json"

        try:
            resp = self.session.request(
                method, url, json=json_data, headers=headers, timeout=30
            )
        except requests.RequestException as e:
            return {"success": False, "error": f"network: {e}"}

        # 401 → re-auth once
        if resp.status_code == 401 and auth and _retry_auth:
            print(f"  🔄 401 on {method} {path} — re-authenticating...")
            self.token = None
            if self.authenticate():
                return self._api(method, path, json_data, auth=True, _retry_auth=False)
            return {"success": False, "error": "401 re-auth failed", "status": 401}

        # 429 → exponential backoff (max 3 retries)
        if resp.status_code == 429 and _attempt < 3:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** (_attempt + 2))
            print(f"  ⚠️  429 on {method} {path}, wait {wait}s (attempt {_attempt + 1}/3)...")
            time.sleep(wait)
            return self._api(method, path, json_data, auth, _retry_auth, _attempt + 1)

        try:
            data = resp.json()
        except ValueError:
            return {
                "success": False,
                "error": f"non-json response ({resp.status_code})",
                "status": resp.status_code,
                "body": resp.text[:300],
            }

        if isinstance(data, dict) and "status" not in data:
            data["_http"] = resp.status_code
        return data if isinstance(data, dict) else {"success": True, "data": data}

    # ─── Auth ────────────────────────────────────────────────────────
    def authenticate(self) -> bool:
        print(f"🔐 Authenticating {self.wallet[:10]}...")
        resp = self._api(
            "POST",
            "/auth/nonce",
            {"walletAddress": self.wallet},
            auth=False,
            _retry_auth=False,
        )
        if not resp.get("success"):
            print(f"  ❌ Nonce failed: {resp}")
            return False

        nonce = resp["data"]["nonce"]
        message = resp["data"]["message"]
        print(f"  📝 Nonce: {nonce[:16]}...")

        sig_hex = self._sign_message(message)
        print(f"  ✍️  Signed: {sig_hex[:20]}...")

        body: dict[str, Any] = {
            "walletAddress": self.wallet,
            "signature": sig_hex,
            "nonce": nonce,
        }
        if self.referral_code:
            body["referralCode"] = self.referral_code

        resp = self._api("POST", "/auth/verify", body, auth=False, _retry_auth=False)
        if not resp.get("success"):
            print(f"  ❌ Verify failed: {resp}")
            return False

        token = resp["data"]["accessToken"]
        user = resp["data"]["user"]
        self._save_token(token)
        print(
            f"  ✅ Auth OK | id={user['id'][:16]}... | pts={user.get('totalPoints')} "
            f"| ref={user.get('referralCode')}"
        )
        return True

    # ─── Node ────────────────────────────────────────────────────────
    def get_node(self) -> Optional[dict]:
        resp = self._api("GET", "/nodes")
        if resp.get("success"):
            return resp.get("data")
        print(f"  ⚠️  get_node failed: {resp}")
        return None

    def activate_node(self) -> Optional[dict]:
        node = self.get_node()
        if node and node.get("status") == "ACTIVE":
            print(f"  ✅ Node already active: {node['nodeId']}")
            return node

        print("⚡ Activating node...")
        resp = self._api("GET", "/nodes/message")
        if not resp.get("success"):
            print(f"  ❌ Failed to get activate message: {resp}")
            return None

        message = resp["data"]["message"]
        print(f"  📝 Signing: {message[:60].replace(chr(10), ' ')}...")
        sig_hex = self._sign_message(message)

        resp = self._api("POST", "/nodes/activate", {"signature": sig_hex})
        if resp.get("success"):
            node = resp["data"]
            pts = node.get("nodeScoreResult", {}).get("pointsAwarded", "?")
            print(f"  ✅ Node activated! ID={node['nodeId']} +{pts} pts")
            return node

        print(f"  ❌ Activation failed: {resp}")
        return None

    def check_in(self) -> Optional[dict]:
        # Prefer pre-check via node state to avoid useless 429 noise
        node = self.get_node()
        if node is not None and node.get("canCheckIn") is False:
            print(
                f"  ℹ️  Already checked in "
                f"(streak={node.get('checkInStreak')}, last={node.get('lastCheckInAt')})"
            )
            return None

        print("📅 Daily check-in...")
        resp = self._api("POST", "/nodes/check-in")
        if resp.get("success"):
            data = resp["data"]
            print(
                f"  ✅ Check-in! +{data.get('pointsAwarded')} pts "
                f"(streak={data.get('streak')})"
            )
            if data.get("leveledUp"):
                print("  🎉 LEVEL UP!")
            return data

        msg = str(resp.get("message") or resp.get("error") or resp)
        low = msg.lower()
        if any(k in low for k in ("already", "checked in", "too many", "rate")):
            print(f"  ℹ️  Skip: {msg}")
        else:
            print(f"  ❌ Check-in failed: {resp}")
        return None

    # ─── Socials ─────────────────────────────────────────────────────
    def get_socials(self) -> list:
        resp = self._api("GET", "/socials")
        if resp.get("success"):
            return resp.get("data") or []
        return []

    def connect_social(self, platform: str, username: str) -> Optional[dict]:
        platform = platform.upper()
        existing = {s.get("platform", "").upper(): s for s in self.get_socials()}
        if platform in existing and existing[platform].get("status") == "VERIFIED":
            print(f"  ✅ {platform} already verified: @{existing[platform].get('username')}")
            return existing[platform]

        print(f"🔗 Connecting {platform}: @{username}...")
        resp = self._api(
            "POST",
            "/socials/connect",
            {"platform": platform, "username": username},
        )
        if resp.get("success"):
            print(f"  ✅ {platform} connect OK for @{username}")
            return resp.get("data")
        print(f"  ❌ {platform} connect failed: {resp.get('message', resp)}")
        return None

    def connect_missing_socials(self, socials: dict[str, str]) -> None:
        if not socials:
            return
        current = {s.get("platform", "").upper() for s in self.get_socials() if s.get("status") == "VERIFIED"}
        for platform, username in socials.items():
            if platform.upper() in current:
                print(f"  ⏭️  {platform} already connected")
                continue
            self.connect_social(platform, username)
            time.sleep(1.5)

    # ─── Info ────────────────────────────────────────────────────────
    def get_activity(self, page: int = 1, limit: int = 20) -> list:
        resp = self._api("GET", f"/users/me/activity?page={page}&limit={limit}")
        if not resp.get("success"):
            return []
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data") or []
        return []

    def get_referrals(self) -> Optional[dict]:
        resp = self._api("GET", "/referrals/stats")
        if resp.get("success"):
            return resp.get("data")
        return None

    def get_missions(self) -> list:
        resp = self._api("GET", "/missions")
        if resp.get("success"):
            return resp.get("data") or []
        return []

    # ─── Status ──────────────────────────────────────────────────────
    def status(self) -> None:
        print("=" * 60)
        print(f"🌐 AWARIZON | {self.wallet}")
        print("=" * 60)

        node = self.get_node()
        if not node:
            print("❌ No node — run --action activate first")
            return

        print(f"\n📡 Node: {node.get('nodeId')} ({node.get('status')})")
        print(f"   Level: {node.get('nodeLevelTitle')} (Lv.{node.get('nodeLevel')})")
        print(f"   Score: {node.get('nodeScore')} pts")
        print(f"   Multiplier: {node.get('nodeMultiplier')}x")
        print(f"   Reputation: {node.get('nodeReputation')}")
        can = node.get("canCheckIn")
        print(
            f"   Check-in: {'✅ available' if can else '❌ already done'} "
            f"(streak={node.get('checkInStreak')})"
        )

        print("\n📊 Score Breakdown:")
        for key in (
            "missionScore",
            "socialScore",
            "checkInScore",
            "referralScore",
            "creatorScore",
            "eventScore",
            "achievementScore",
        ):
            val = node.get(key, 0) or 0
            if val:
                print(f"   {key.replace('Score', '').title()}: {val}")

        prog = node.get("progress") or {}
        nxt = prog.get("nextLevel") or {}
        if nxt:
            score = float(node.get("nodeScore") or 0)
            target = float(nxt.get("minScore") or 1)
            pct = min(100.0, (score / max(target, 1)) * 100)
            print(f"\n🎯 Progress to {nxt.get('title')}: {int(score)}/{int(target)} ({pct:.0f}%)")

        socials = self.get_socials()
        print(f"\n🔗 Socials: {len(socials)}")
        for s in socials:
            print(f"   {s.get('platform')}: @{s.get('username')} ({s.get('status')})")

        refs = self.get_referrals()
        if refs:
            print(f"\n👥 Referrals: {refs.get('totalReferrals')} (code={refs.get('code')})")
            print(f"🔗 Link: {refs.get('url')}")

        missions = self.get_missions()
        print(f"\n📋 Missions: {len(missions)} available")
        for m in missions[:5]:
            print(f"   - {m}")

        act = self.get_activity(limit=5)
        if act:
            print("\n📜 Recent Activity:")
            for a in act[:5]:
                print(f"   +{a.get('amount')} pts — {a.get('description')}")

        print("=" * 60)

    # ─── Auto farm ───────────────────────────────────────────────────
    def auto(self, socials: Optional[dict[str, str]] = None) -> dict:
        """Full daily flow for one wallet. Returns summary dict."""
        summary = {
            "wallet": self.wallet,
            "activated": False,
            "checkin": False,
            "socials": 0,
            "score": None,
            "error": None,
        }
        try:
            if not self.token or self._jwt_expired(self.token):
                if not self.authenticate():
                    summary["error"] = "auth_failed"
                    return summary

            node = self.activate_node()
            summary["activated"] = bool(node and node.get("status") == "ACTIVE")
            time.sleep(1)

            if socials:
                before = len(self.get_socials())
                self.connect_missing_socials(socials)
                after = len(self.get_socials())
                summary["socials"] = max(0, after - before)
                time.sleep(1)

            result = self.check_in()
            summary["checkin"] = bool(result)
            time.sleep(1)

            node = self.get_node() or {}
            summary["score"] = node.get("nodeScore")
            summary["nodeId"] = node.get("nodeId")
            summary["canCheckIn"] = node.get("canCheckIn")
            summary["streak"] = node.get("checkInStreak")
        except Exception as e:
            summary["error"] = str(e)
            print(f"  ❌ auto error: {e}")
        return summary


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Awarizon Testnet Bot v2")
    parser.add_argument(
        "--action",
        default="status",
        choices=["status", "activate", "checkin", "social", "auto"],
        help="Action to perform",
    )
    parser.add_argument("--platform", help="Social platform (TWITTER, DISCORD, TELEGRAM)")
    parser.add_argument("--username", help="Social username")
    parser.add_argument("--wallet", default=DEFAULT_WALLET, help="Single wallet file (JSON or plain txt)")
    parser.add_argument(
        "--wallets-dir",
        help="Directory of wallets: pk.txt (multi-key), *.json, *.txt, *.key",
    )
    parser.add_argument("--referral", default=DEFAULT_REFERRAL, help="Referral code")
    parser.add_argument(
        "--twitter",
        help="Twitter username for auto connect",
    )
    parser.add_argument(
        "--telegram",
        help="Telegram username for auto connect",
    )
    parser.add_argument(
        "--discord",
        help="Discord username for auto connect",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay seconds between wallets in batch mode",
    )
    args = parser.parse_args()

    socials = dict(DEFAULT_SOCIALS)
    if args.twitter:
        socials["TWITTER"] = args.twitter
    if args.telegram:
        socials["TELEGRAM"] = args.telegram
    if args.discord:
        socials["DISCORD"] = args.discord

    # ── Load wallets ──────────────────────────────────────────────────
    if args.wallets_dir:
        # Batch mode: load from directory (pk.txt + json + txt + key)
        try:
            wallets = load_wallets_from_dir(args.wallets_dir)
        except Exception as e:
            print(f"❌ Wallet dir error: {e}")
            sys.exit(1)
    else:
        # Single wallet mode
        try:
            addr, pk = load_wallet(os.path.expanduser(args.wallet))
            wallets = [(addr, pk)]
        except Exception as e:
            print(f"❌ Wallet load error: {e}")
            sys.exit(1)

    results = []
    for i, (addr, pk) in enumerate(wallets):
        print(f"\n{'─' * 60}")
        print(f"👛 Wallet: {addr[:14]}... ({i + 1}/{len(wallets)})")
        try:
            client = AwarizonClient(addr, pk, referral_code=args.referral)

            if args.action == "status":
                client.status()
                results.append({"wallet": addr, "action": args.action, "ok": True})
            elif args.action == "activate":
                node = client.activate_node()
                results.append({"wallet": addr, "action": args.action, "ok": bool(node)})
            elif args.action == "checkin":
                r = client.check_in()
                results.append({"wallet": addr, "action": args.action, "ok": True})
            elif args.action == "social":
                if not args.platform or not args.username:
                    print("❌ Need --platform and --username")
                    results.append({"wallet": addr, "action": args.action, "ok": False})
                else:
                    r = client.connect_social(args.platform, args.username)
                    results.append({"wallet": addr, "action": args.action, "ok": bool(r)})
            elif args.action == "auto":
                print("🚀 Auto-farm...")
                r = client.auto(socials=socials)
                results.append(r)
            else:
                print(f"❌ Unknown action: {args.action}")
                results.append({"wallet": addr, "action": args.action, "ok": False})
        except Exception as e:
            print(f"❌ Failed: {e}")
            results.append({"wallet": addr, "error": str(e), "ok": False})
        if i < len(wallets) - 1:
            time.sleep(args.delay)

    if len(results) > 1:
        print(f"\n{'=' * 60}")
        print(f"📦 Batch summary: {len(results)} wallets")
        ok = sum(1 for r in results if r.get("ok") or r.get("score") is not None)
        print(f"   OK-ish: {ok}/{len(results)}")
        for r in results:
            w = r.get("wallet", "?")
            if isinstance(w, str) and w.startswith("0x"):
                w = w[:10] + "..."
            score = r.get("score")
            err = r.get("error")
            print(f"   - {w} score={score} err={err}")
        print("=" * 60)


if __name__ == "__main__":
    main()
