# Telegram AI Agent Bot

A Telegram bot front-end for the AI agent built in [ai-agent-practice](https://github.com/qwertylee538-dot/ai-agent-practice) —
the same agentic loop (DeepSeek API + tool calling: currency exchange
rates and a calculator), now reachable from Telegram instead of a
terminal.

## Key idea

The agent's "brain" (`run_agent()` and its tools) is unchanged from the
terminal version — it doesn't know or care whether a question came from
`input()` or from a Telegram message. Only the "front door" is new:
`python-telegram-bot` receives messages and hands the text to the same
`run_agent()` function, then sends the returned answer back as a reply.

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
(e.g. "How much is 250 USD in RUB?"). Press Ctrl+C in the terminal to
stop the bot.

## Tech stack

`python-telegram-bot` (Telegram Bot API wrapper), `openai` SDK pointed
at DeepSeek's API, `requests` for the exchange rate lookup,
`python-dotenv` for safe secret loading.

## License

MIT.
