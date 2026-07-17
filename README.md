# Awarizon Testnet Bot 🌐

Automated farmer for [Awarizon Testnet](https://testnet.awarizon.com) — SIWE auth, node activation, daily check-in, social connect.

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

## Setup

```bash
# Copy and fill your .env
cp .env.example .env
```

Edit `.env`:
```env
# Single wallet
PRIVATE_KEY=0xYOUR_PRIVATE_KEY_HERE

# Multi-wallet (comma-separated)
PRIVATE_KEY=0xkey1,0xkey2,0xkey3

# Optional
REFERRAL_CODE=YOUR_CODE
TWITTER_USERNAME=yourhandle
TELEGRAM_USERNAME=yourname
DISCORD_USERNAME=yourname
```

## Usage

```bash
# Check status
python3 awarizon_bot.py --action status

# Activate node (once)
python3 awarizon_bot.py --action activate

# Daily check-in
python3 awarizon_bot.py --action checkin

# Connect social (+200 each, once)
python3 awarizon_bot.py --action social --platform TWITTER --username yourhandle

# Full auto (activate + check-in + auto-connect socials from .env)
python3 awarizon_bot.py --action auto
```

## Multi-Wallet

Comma-separated in `.env`:
```env
PRIVATE_KEY=0xabc...,0xdef...,0x123...
```

Or use `PRIVATE_KEY_2`, `PRIVATE_KEY_3`, etc:
```env
PRIVATE_KEY=0xabc...
PRIVATE_KEY_2=0xdef...
PRIVATE_KEY_3=0x123...
```

All wallets process automatically in batch with `--action auto`.

## CLI Options

```
--action      status | activate | checkin | social | auto
--platform    TWITTER | DISCORD | TELEGRAM
--username    Social username (for --action social)
--referral    Referral code override (overrides .env)
--twitter     Twitter handle override (overrides .env)
--telegram    Telegram username override (overrides .env)
--discord     Discord username override (overrides .env)
--delay       Seconds between wallets in batch (default: 2)
```

## Cron (Daily Auto)

```bash
# Add to crontab — runs daily at 08:00 UTC (15:00 WIB)
0 8 * * * cd /path/to/awarizon-testnet-bot && python3 awarizon_bot.py --action auto
```

## API Flow

```
Auth:   POST /auth/nonce → sign message → POST /auth/verify → JWT
Node:   GET /nodes/message → sign → POST /nodes/activate → +500 pts
Daily:  POST /nodes/check-in → +20 pts (streak bonus)
Social: POST /socials/connect {platform, username} → +200 pts each
```

## Security

- Private keys live in `.env` only (gitignored, chmod 600)
- JWT tokens cached per wallet in `~/.awarizon/tokens/`
- Auto re-auth on HTTP 401 or JWT expiry
- Exponential backoff on HTTP 429 (max 3 retries)
- Token files `chmod 600`

## Requirements

- Python 3.10+
- `requests`
- `eth-account`

## Disclaimer

This tool is for educational and testing purposes. Use at your own risk. Not affiliated with Awarizon.
