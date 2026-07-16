# Awarizon Testnet Bot 🌐

Automated farmer for [Awarizon Testnet](https://testnet.awarizon.com) — SIWE auth, node activation, daily check-in, social connect, multi-wallet batch farming.

## Features

| Feature | Points | Frequency |
|---|---|---|
| Node activation | +500 | Once |
| Twitter connect | +200 | Once |
| Telegram connect | +200 | Once |
| Discord connect | +200 | Once |
| Daily check-in | +20 | Daily (+streak) |
| Referral bonus | Varies | Per referral |

## Install

```bash
git clone https://github.com/kaidenzeto/awarizon-testnet-bot.git
cd awarizon-testnet-bot
pip install requests eth-account
```

## Quick Start

```bash
# Set your wallet path
export WALLET_PATH=/path/to/wallet.json

# 1. Check status
python3 awarizon_bot.py --action status --wallet $WALLET_PATH

# 2. Activate node (once)
python3 awarizon_bot.py --action activate --wallet $WALLET_PATH

# 3. Connect socials (+200 each, once)
python3 awarizon_bot.py --action social --wallet $WALLET_PATH \
  --platform TWITTER --username yourhandle

# 4. Daily check-in (+20/day)
python3 awarizon_bot.py --action checkin --wallet $WALLET_PATH

# 5. Full auto (activate + check-in + optional socials)
python3 awarizon_bot.py --action auto --wallet $WALLET_PATH \
  --twitter yourhandle --telegram yourname --discord yourname#0000
```

## Multi-Wallet Batch

Process all wallets in a directory:

```bash
python3 awarizon_bot.py --action auto --wallets-dir ./wallets/
```

Each wallet file should be a JSON with a `privateKey` field.

## CLI Options

```
--action      status | activate | checkin | social | auto
--wallet      Path to single wallet JSON
--wallets-dir Directory of wallet JSONs (batch mode)
--referral    Referral code (optional)
--platform    TWITTER | DISCORD | TELEGRAM
--username    Social username to connect
--twitter     Twitter handle (for auto connect)
--telegram    Telegram username (for auto connect)
--discord     Discord username (for auto connect)
--delay       Seconds between wallets in batch (default: 2)
```

## Cron (Daily Auto)

```bash
# Add to crontab (15:00 WIB / 08:00 UTC daily)
0 8 * * * python3 /path/to/awarizon_bot.py --action auto --wallet /path/to/wallet.json
```

Or use the included wrapper:
```bash
chmod +x checkin_cron.sh
0 8 * * * /path/to/checkin_cron.sh
```

## API Flow

```
Auth:   POST /auth/nonce → sign message → POST /auth/verify → JWT
Node:   GET /nodes/message → sign → POST /nodes/activate → +500 pts
Daily:  POST /nodes/check-in → +20 pts (streak bonus)
Social: POST /socials/connect {platform, username} → +200 pts each
```

## JWT Auto-Refresh

- Token cached per wallet in `~/.awarizon/tokens/`
- Auto re-auth on HTTP 401 or JWT expiry
- Exponential backoff on HTTP 429 (max 3 retries)
- Token files `chmod 600` for security

## Requirements

- Python 3.10+
- `requests`
- `eth-account`

## Disclaimer

This tool is for educational and testing purposes. Use at your own risk. Not affiliated with Awarizon.
