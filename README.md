# Telegram AI Agent Bot

A Telegram bot front-end for the AI agent built in [ai-agent-practice](https://github.com/qwertylee538-dot/ai-agent-practice) —
the same agentic loop (DeepSeek API + tool calling), now reachable from
Telegram instead of a terminal, with per-user conversation memory and
live crypto market data added on top.

## What it can do

- **Chat with memory** — remembers earlier messages in the conversation
  (per Telegram chat), so follow-ups like "and in euros?" work naturally.
  Send `/reset` any time to clear the history and start fresh.
- **Currency exchange rates** — e.g. "How much is 250 USD in RUB?"
- **Math** — any arithmetic expression, evaluated safely by a dedicated
  tool rather than left to the model to compute itself.
- **Crypto market data** (via [CoinGecko](https://www.coingecko.com)'s
  public API, no key required):
  - live price, 24h change, 24h volume and market cap for a coin
  - search by name or ticker symbol to find a coin's exact id (works
    for practically any coin, not just the famous ones)
  - a "what's trending right now" lookup
  - the bot only ever reports facts — it's explicitly instructed to
    never give buy/sell/investment advice or predictions

## Key idea

The agent's "brain" (`run_agent()` and its tools) works the same way
regardless of where the question comes from — it doesn't know or care
whether it's a terminal `input()` or a Telegram message. Only the
"front door" is new: `python-telegram-bot` receives messages, hands
the text (plus that chat's remembered history) to `run_agent()`, and
sends the returned answer back as a reply.

## Install

```bash
pip install -r requirements.txt
```

## Setup

1. Copy `.env.example` to `.env`.
2. Add your DeepSeek API key (from [platform.deepseek.com](https://platform.deepseek.com)) as `DEEPSEEK_API_KEY`.
3. Add your Telegram bot token (from [@BotFather](https://t.me/BotFather)) as `TELEGRAM_BOT_TOKEN`.

`.env` is listed in `.gitignore` and never committed.

## Run

```bash
python bot.py
```

Then open Telegram, find your bot, and send it `/start` or any question
(e.g. "What's the bitcoin price?" or "How much is 250 USD in RUB?").
Press Ctrl+C in the terminal to stop the bot.

## Notes on scope

- Conversation memory lives in the bot's RAM only — it resets if the
  bot process restarts. For a small demo or freelance job that's a
  reasonable trade-off; a production bot would persist it to a file
  or database instead.
- Network hiccups (Telegram, DeepSeek, or CoinGecko being briefly slow
  or unreachable) are caught and reported to the user rather than
  crashing the bot for everyone else.

## Tech stack

`python-telegram-bot` (Telegram Bot API wrapper), `openai` SDK pointed
at DeepSeek's API, `requests` for exchange rate and crypto lookups,
`python-dotenv` for safe secret loading.

## License

MIT.
