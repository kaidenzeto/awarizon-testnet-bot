#!/usr/bin/env python3
"""
Awarizon cron summary — Telegram-friendly output.
Runs auto farm + fetches status, formats a clean card for Telegram.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

BOT = "/root/awarizon-bot/awarizon_bot.py"
WALLET = os.environ.get("AWARIZON_WALLET", "/root/.dac-bot/wallet.json")
PYTHON = sys.executable or "python3"
WIB = timezone(timedelta(hours=7))


def run(action: str, extra: list[str] | None = None) -> str:
    """Run awarizon_bot.py and capture stdout."""
    cmd = [PYTHON, BOT, "--action", action, "--wallet", WALLET]
    if extra:
        cmd.extend(extra)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"❌ Timeout (120s) on {action}"
    except Exception as e:
        return f"❌ Error: {e}"


def parse(raw: str) -> dict:
    """Extract key data from bot stdout."""
    info = {
        "wallet": "?", "node": "?", "status": "?", "level": "?",
        "score": 0, "streak": 0, "checkin_done": False,
        "socials": 0, "total_socials": 3, "pct": 0, "next_level": "?",
        "multiplier": "?", "reputation": 0,
        "act_score": 0, "soc_score": 0, "ref_score": 0,
        "error": None,
    }
    for raw_line in raw.splitlines():
        # Strip leading/trailing whitespace for matching
        l = raw_line.strip()
        # Remove emoji prefix for cleaner matching
        import re
        clean = re.sub(r'^[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2705\u2B55\u274C\u2764\uFE0F]+\s*', '', l).strip()
        
        if "AWARIZON" in l and "|" in l:
            info["wallet"] = l.split("|")[-1].strip()
        if clean.startswith("Node:"):
            info["node"] = clean.split(":", 1)[-1].strip().split("(")[0].strip()
            if "(" in clean:
                info["status"] = clean.split("(")[-1].rstrip(")")
        if clean.startswith("Level:"):
            info["level"] = clean.split(":", 1)[-1].strip()
        if clean.startswith("Score:"):
            try: info["score"] = int(clean.split(":", 1)[-1].strip().split()[0])
            except ValueError: pass
        if clean.startswith("Check-in:") or "Check-in" in clean:
            info["checkin_done"] = "already done" in clean.lower() or "done" in clean.lower()
            if "streak=" in clean:
                try:
                    s = clean.split("streak=")[-1].split(")")[0].split(",")[0]
                    info["streak"] = int(s.strip())
                except (ValueError, IndexError): pass
        if clean.startswith("Socials:"):
            try: info["socials"] = int(clean.split(":", 1)[-1].strip().split("/")[0].split()[0])
            except (ValueError, IndexError): pass
        if clean.startswith("Progress to"):
            try:
                after = clean.split("to ", 1)[-1]
                info["next_level"] = after.split(":")[0].strip()
                pct = after.split("(")[-1].rstrip(") %")
                info["pct"] = int(pct.replace("%", "").strip())
            except (ValueError, IndexError): pass
        if clean.startswith("Multiplier:"):
            info["multiplier"] = clean.split(":", 1)[-1].strip()
        if clean.startswith("Reputation:"):
            try: info["reputation"] = int(clean.split(":", 1)[-1].strip())
            except ValueError: pass
        if clean.startswith("Mission:"):
            try: info["act_score"] = int(clean.split(":", 1)[-1].strip())
            except ValueError: pass
        if clean.startswith("Social:"):
            try: info["soc_score"] = int(clean.split(":", 1)[-1].strip())
            except ValueError: pass
        if clean.startswith("Referral:"):
            try: info["ref_score"] = int(clean.split(":", 1)[-1].strip())
            except ValueError: pass
        if "Check-in!" in clean:
            info["checkin_done"] = True
        if "LEVEL UP" in clean.upper():
            info["error"] = "🎉 LEVEL UP!"
    return info


def card(info: dict) -> str:
    """Format Telegram-friendly card."""
    now = datetime.now(WIB)
    date = now.strftime("%d %b %Y • %H:%M WIB")

    ci = "✅ +20 pts" if not info["checkin_done"] else "⏭️ done"
    streak = info["streak"]
    if streak > 1:
        ci += f" • streak {streak}🔥"
    elif not info["checkin_done"]:
        ci += f" • day 1"

    bar_len = 10
    filled = int(info["pct"] / 100 * bar_len)
    bar = "▓" * filled + "░" * (bar_len - filled)

    msg = f"""🌐 **Awarizon Testnet**
📅 {date}
👛 `{info['wallet']}`

📡 Node: `{info['node']}` ({info['status']})
📊 Level: {info['level']} {info['multiplier']}
⭐ Score: **{info['score']}** pts

📅 Check-in: {ci}
🔗 Socials: {info['socials']}/{info['total_socials']}

🎯 {info['next_level']}
`{bar}` {info['pct']}%"""

    if info["act_score"] or info["soc_score"] or info["ref_score"]:
        parts = []
        if info["act_score"]: parts.append(f"📋Mission:{info['act_score']}")
        if info["soc_score"]: parts.append(f"🐦Social:{info['soc_score']}")
        if info["ref_score"]: parts.append(f"👥Ref:{info['ref_score']}")
        msg += "\n\n💰 " + " • ".join(parts)

    if info["error"]:
        msg += f"\n\n{info['error']}"

    return msg


if __name__ == "__main__":
    # 1. Run auto (activate + checkin)
    auto_raw = run("auto")

    # 2. Run status to get full details
    status_raw = run("status")

    # 3. Parse and merge
    info = parse(status_raw)
    # Override checkin status from auto output if available
    if "Check-in!" in auto_raw:
        info["checkin_done"] = False
    if "Already checked in" in auto_raw or "already done" in auto_raw:
        info["checkin_done"] = True

    print(card(info))
