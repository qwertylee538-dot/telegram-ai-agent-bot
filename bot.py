"""
Telegram bot front-end for our AI agent -- with conversation memory and
three crypto market tools (CoinGecko).

WHAT CHANGED vs the first version:
1. CONVERSATION MEMORY -- each Telegram chat has a unique chat_id. We
   keep a dictionary {chat_id: messages_list} so every user gets their
   own remembered conversation. Before, we built a fresh `messages`
   list on every single question, so the bot had no memory at all.
   NOTE: this memory lives only in this program's RAM -- if the bot
   restarts, all conversations are forgotten. For a real production
   bot you'd persist this to a file or database, but for a demo (and
   most small freelance jobs) in-memory is a perfectly normal choice.
2. CRYPTO TOOLS (CoinGecko's public API, no key needed):
   - get_crypto_data() -- live price + 24h stats for a known coin id.
   - search_crypto() -- look up a coin's exact id by name/ticker, so
     the bot can handle practically any coin, not just famous ones.
   - get_trending_crypto() -- what's currently trending worldwide.
   We started with Binance's public API but it blocks requests from
   some regions (including Russia) with a "restricted location" error,
   so we switched to CoinGecko, which has no such geo-restriction.
   The system prompt explicitly tells the model to report facts only,
   never give buy/sell advice -- that's a deliberate safety choice.
3. RESILIENCE -- network hiccups (a slow Telegram/DeepSeek/CoinGecko
   response) are caught with try/except around each risky call, plus
   a global error handler, so one bad moment no longer crashes the
   whole bot for every user.
4. PERSISTENT MEMORY -- conversation history now lives in a SQLite
   database file (see db.py) instead of a plain Python dict in RAM.
   This means the bot restarting no longer wipes everyone's chat
   history -- it's saved to disk after every turn.
"""

import json
import os

import requests
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

import db

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY not found -- check your .env file.")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not found -- check your .env file.")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "Always use the calculate tool for any arithmetic -- never compute "
    "numbers yourself. When asked about crypto prices, use the "
    "get_crypto_data tool and report the facts (price, 24h change, "
    "high/low) plainly -- never give buy/sell/investment advice or "
    "predictions, you only report data. Keep answers concise, this is "
    "a chat interface. Remember the earlier parts of this conversation "
    "when the user refers back to something (e.g. 'and in euros?')."
)

# ---------------------------------------------------------------------------
# CONVERSATION MEMORY -- now backed by SQLite (see db.py) instead of a
# plain Python dict, so it survives bot restarts.
# ---------------------------------------------------------------------------

# Safety cap: how many past messages we load per conversation. Without
# this, a long-running chat would keep growing forever, costing more
# tokens (money) on every single message.
MAX_HISTORY_MESSAGES = 20


def get_history(chat_id: int) -> list:
    """Return this chat's message history as a list ready for the
    DeepSeek API: the system prompt, followed by the most recent
    messages loaded from the database (oldest first).
    """
    past_messages = db.load_history(chat_id, limit=MAX_HISTORY_MESSAGES - 1)
    return [{"role": "system", "content": SYSTEM_PROMPT}] + past_messages


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def get_exchange_rate(base_currency: str, target_currency: str) -> str:
    """Look up a live exchange rate via a free public API (open.er-api.com)."""
    try:
        response = requests.get(
            f"https://open.er-api.com/v6/latest/{base_currency.upper()}",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            return f"Exchange rate service returned an error: {data.get('error-type', 'unknown error')}"

        rate = data.get("rates", {}).get(target_currency.upper())
        if rate is None:
            return f"Could not find a rate for {target_currency} (check the currency code)."

        return (
            f"1 {base_currency.upper()} = {rate} {target_currency.upper()} "
            f"(last updated: {data.get('time_last_update_utc')})"
        )
    except requests.exceptions.RequestException as exc:
        return f"Error while fetching exchange rate: {exc}"


def calculate(expression: str) -> str:
    """Safely evaluate a simple arithmetic expression, e.g. '250 * 86.41'."""
    import re

    allowed_pattern = r"^[0-9\.\s\+\-\*/\(\)]+$"
    if not re.match(allowed_pattern, expression):
        return "Error: expression contains characters that are not allowed."

    try:
        result = eval(expression)
        return str(result)
    except Exception as exc:
        return f"Error evaluating expression: {exc}"


def get_crypto_data(coin_id: str) -> str:
    """Look up live price + 24h stats for a cryptocurrency from
    CoinGecko's PUBLIC API -- no API key or account needed.

    NOTE: we use CoinGecko instead of Binance here specifically because
    Binance's API blocks requests from some regions (including Russia)
    with a "restricted location" error -- CoinGecko has no such
    geo-restriction, so it's the more reliable choice for this bot.

    `coin_id` is CoinGecko's own id for the coin, e.g. 'bitcoin',
    'ethereum', 'solana', 'dogecoin' -- lowercase, full name, not the
    ticker symbol. The model is told this in the tool description below.
    """
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_id.lower(),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        coin_data = data.get(coin_id.lower())
        if not coin_data:
            return (
                f"Could not find a coin with id '{coin_id}'. Use CoinGecko's "
                "coin id (e.g. 'bitcoin', 'ethereum', 'solana'), not the ticker symbol."
            )

        price = coin_data.get("usd")
        change_pct = coin_data.get("usd_24h_change")
        volume = coin_data.get("usd_24h_vol")
        market_cap = coin_data.get("usd_market_cap")

        # CoinGecko doesn't always have every field for every coin (small
        # or new coins especially) -- format each one defensively so a
        # missing value shows as "N/A" instead of crashing the bot.
        def fmt_usd(value):
            return f"${value:,.2f}" if value is not None else "N/A"

        def fmt_pct(value):
            return f"{value:+.2f}%" if value is not None else "N/A"

        return (
            f"{coin_id.capitalize()}: price = {fmt_usd(price)} | "
            f"24h change = {fmt_pct(change_pct)} | "
            f"24h volume = {fmt_usd(volume)} | market cap = {fmt_usd(market_cap)}. "
            "(This is market data only, not financial advice.)"
        )
    except requests.exceptions.RequestException as exc:
        return f"Error while fetching crypto data: {exc}"


def search_crypto(query: str) -> str:
    """Search CoinGecko for a coin by name or ticker symbol and return
    the matching coin id(s) -- this is what makes get_crypto_data work
    for practically ANY coin, not just the famous ones the model
    already knows the id for. The model is expected to call this
    FIRST when it isn't sure of the exact id, then call
    get_crypto_data with the id this returns.
    """
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": query},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        coins = data.get("coins", [])[:5]  # top 5 matches is plenty
        if not coins:
            return f"No coins found matching '{query}'."

        matches = [f"{c['name']} (ticker: {c['symbol'].upper()}, id: {c['id']})" for c in coins]
        return "Matches found:\n" + "\n".join(matches)
    except requests.exceptions.RequestException as exc:
        return f"Error while searching for crypto: {exc}"


def get_trending_crypto() -> str:
    """Return the coins currently most searched-for on CoinGecko
    worldwide -- a free, no-argument 'what's hot right now' endpoint.
    """
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        coins = data.get("coins", [])[:7]
        if not coins:
            return "Could not fetch trending coins right now."

        lines = [
            f"{i + 1}. {c['item']['name']} ({c['item']['symbol'].upper()})"
            for i, c in enumerate(coins)
        ]
        return "Currently trending on CoinGecko:\n" + "\n".join(lines)
    except requests.exceptions.RequestException as exc:
        return f"Error while fetching trending coins: {exc}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Get the current exchange rate between two currencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base_currency": {"type": "string", "description": "3-letter code, e.g. USD"},
                    "target_currency": {"type": "string", "description": "3-letter code, e.g. RUB"},
                },
                "required": ["base_currency", "target_currency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a simple arithmetic expression (numbers and + - * / ( ) only). "
                "Use this for any multiplication, division, or other math the user's "
                "question requires -- do not do arithmetic yourself, always call this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "e.g. '250 * 86.41'"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_data",
            "description": (
                "Get the live price and 24-hour stats (change %, volume, market cap) "
                "for a cryptocurrency, via CoinGecko. Use this whenever the user asks "
                "about a crypto price or the crypto market."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "coin_id": {
                        "type": "string",
                        "description": (
                            "CoinGecko's own id for the coin, lowercase full name, "
                            "e.g. 'bitcoin', 'ethereum', 'solana', 'dogecoin' -- "
                            "NOT the ticker symbol (not 'BTC'). If you are not "
                            "confident of the exact id, call search_crypto first."
                        ),
                    },
                },
                "required": ["coin_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_crypto",
            "description": (
                "Search for a cryptocurrency by name or ticker symbol and get back "
                "its exact CoinGecko id. Use this BEFORE get_crypto_data whenever "
                "you're not 100% sure of a coin's exact id (e.g. lesser-known coins)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Coin name or ticker, e.g. 'shiba inu' or 'PEPE'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending_crypto",
            "description": "Get the list of coins currently most searched-for / trending worldwide right now.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

AVAILABLE_FUNCTIONS = {
    "get_exchange_rate": get_exchange_rate,
    "calculate": calculate,
    "get_crypto_data": get_crypto_data,
    "search_crypto": search_crypto,
    "get_trending_crypto": get_trending_crypto,
}


# ---------------------------------------------------------------------------
# The agent's "brain" -- now takes and returns a `messages` list instead
# of building one internally, so the caller can persist it as memory.
# ---------------------------------------------------------------------------
def run_agent(messages: list, max_iterations: int = 5) -> str:
    """Run the agentic loop on an existing `messages` conversation
    (which already ends with the user's new question appended) and
    return the final text answer. `messages` is mutated in place with
    every tool call/result, so the caller's stored history stays
    up to date automatically.
    """
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
        )
        response_message = response.choices[0].message

        if not response_message.tool_calls:
            messages.append({"role": "assistant", "content": response_message.content})
            return response_message.content

        messages.append(response_message)

        for tool_call in response_message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            function_to_call = AVAILABLE_FUNCTIONS[function_name]
            function_result = function_to_call(**function_args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": function_result,
                }
            )

    return "Sorry, I couldn't complete this request within the allowed number of steps."


# ---------------------------------------------------------------------------
# Telegram "front door"
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs when a user sends /start."""
    # Reset this chat's memory so /start always begins a clean conversation.
    db.clear_history(update.message.chat_id)
    await update.message.reply_text(
        "Hi! I'm an AI assistant. Ask me anything -- I can look up currency "
        "exchange rates, crypto prices/search/trending coins (CoinGecko), do "
        "math, and I'll remember our conversation (even if the bot restarts). "
        "Send /reset any time to start fresh."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs when a user sends /reset -- clears just this chat's memory."""
    db.clear_history(update.message.chat_id)
    await update.message.reply_text("Conversation history cleared. Fresh start!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every time a user sends a normal (non-command) text message."""
    chat_id = update.message.chat_id
    user_question = update.message.text

    # send_chat_action is purely cosmetic (the "typing..." indicator) --
    # if THIS specific call has a network hiccup, it must never take
    # down the whole bot over something so minor, so we swallow errors
    # here and just skip the indicator that one time.
    try:
        await update.message.chat.send_action(action="typing")
    except Exception:
        pass

    # Load past history from the database, then add this new question.
    # NOTE: we save the user's question to the database right away --
    # even if something goes wrong further down, we don't lose the
    # record that they asked it.
    messages = get_history(chat_id)
    messages.append({"role": "user", "content": user_question})
    db.save_message(chat_id, "user", user_question)

    try:
        answer = run_agent(messages)
    except Exception as exc:
        # Something failed inside the agent loop itself (DeepSeek API
        # hiccup, network issue, etc.) -- tell the user plainly instead
        # of crashing the whole bot process for every other user too.
        print(f"[error] run_agent failed: {exc}")
        await update.message.reply_text(
            "Sorry, something went wrong on my end processing that. Please try again."
        )
        return

    # Save the assistant's reply too, so next turn's get_history() sees
    # this full exchange. We only persist the final text answer here
    # (not the intermediate tool-call steps run_agent used internally)
    # -- that's all a future turn needs to "remember" the conversation.
    db.save_message(chat_id, "assistant", answer)

    try:
        await update.message.reply_text(answer)
    except Exception as exc:
        print(f"[error] failed to send reply: {exc}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catches any exception python-telegram-bot itself raises while
    processing an update (e.g. a network timeout in the library's own
    internals) so it's logged instead of crashing the whole bot.
    """
    print(f"[error] Unhandled exception: {context.error}")


def main() -> None:
    # Make sure the messages table exists before we start handling
    # any updates -- safe to call every startup, it's a no-op if the
    # table is already there.
    db.init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Registers our error_handler as the catch-all for exceptions the
    # library itself hits (e.g. a network timeout mid-request) -- this
    # is what stops one bad network moment from crashing the whole bot.
    app.add_error_handler(error_handler)

    print("Bot is running. Open Telegram and message your bot. Press Ctrl+C here to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
