import os
import re
import json
import logging
import discord
import httpx
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('aossie-bot')

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID')
DISCORD_CHANNEL_ID_INT = None
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')
SKILL_FILE_PATH = os.getenv('SKILL_FILE_PATH', '.clinerules')
OLLAMA_URL = "http://localhost:11434/api/generate"
GAP_LOG_PATH = Path("gap_log.json")
MAX_RETRIES = 3

# Initialize bot with intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Lock to prevent Ollama requests from clashing
ollama_lock = asyncio.Lock()

THREAD_HISTORY_LIMIT = 10  # messages to pull from thread as conversation context


def clean_bot_mention(content: str) -> str:
    """Remove a leading mention of the bot from the content."""
    if client.user:
        content = re.sub(
            rf'^\s*(?:<@!?{client.user.id}>\s*)+',
            '',
            content,
            count=1,
        )
    return content.strip()


def _load_gap_log():
    if GAP_LOG_PATH.exists():
        try:
            with open(GAP_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("gap_log.json corrupted, starting fresh")
    return []


def _save_gap_log(entries):
    GAP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GAP_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)

gap_log_lock = asyncio.Lock()

async def _log_gap(query, reason, thread_id=None):
 async with gap_log_lock:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "reason": reason,
    }
    if thread_id:
        entry["thread_id"] = thread_id
    entries = _load_gap_log()
    entries.append(entry)
    _save_gap_log(entries)
    logger.info(f"Gap logged: {reason} — query: {query[:80]}")


def load_skill_context() -> str:
    """Load context from the local skill file."""
    try:
        if os.path.exists(SKILL_FILE_PATH):
            with open(SKILL_FILE_PATH, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error loading skill file {SKILL_FILE_PATH}: {e}")
    return ""


async def generate_ollama_response(prompt: str, context: str) -> tuple[str, bool]:
    """Send prompt to local Ollama instance. Returns (response_text, used_llm_fallback)."""
    if context:
        system_prompt = f"You are a helpful contributor assistant for AOSSIE.\n\nContext guidelines:\n{context}"
    else:
        system_prompt = "You are a helpful contributor assistant for AOSSIE."

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                response = await http_client.post(OLLAMA_URL, json=payload)
                response.raise_for_status()
                data = response.json()
                text = data.get("response", "")
                if text:
                    return text, False  # False = Ollama succeeded, no fallback gap
                logger.warning(f"Empty Ollama response (attempt {attempt}/{MAX_RETRIES})")
        except httpx.TimeoutException:
            logger.error(f"Ollama timed out (attempt {attempt}/{MAX_RETRIES})")
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error {e.response.status_code} (attempt {attempt}/{MAX_RETRIES}): {e}")
            if e.response.status_code == 404:
                err_msg = (
                    f"I'm sorry, the local Ollama model '{OLLAMA_MODEL}' was not found (HTTP 404).\n"
                    f"Please contact @kpj2006 or run `ollama pull {OLLAMA_MODEL}` on your machine."
                )
                return err_msg, True
            elif 400 <= e.response.status_code < 500:
                err_msg = (
                    f"Local Ollama configuration or client error (HTTP {e.response.status_code}).\n"
                    f"Details: {e.response.text}"
                )
                return err_msg, True
        except httpx.RequestError as e:
            logger.error(f"Ollama unreachable (attempt {attempt}/{MAX_RETRIES}): {e}")
        except Exception as e:
            logger.error(f"Ollama error (attempt {attempt}/{MAX_RETRIES}): {e}")
        if attempt < MAX_RETRIES:
            await asyncio.sleep(2)

    return "I'm sorry, the local AI model is currently unavailable. Please try again later or ask a maintainer.", True


async def _build_conversation_context(thread: discord.Thread, current_author: discord.User, current_query: str) -> str:
    """Pull recent thread history and format it as conversation context for Ollama."""
    history_parts = []
    try:
        async for msg in thread.history(limit=THREAD_HISTORY_LIMIT, oldest_first=True):
            content_cleaned = clean_bot_mention(msg.content)
            if msg.author.bot:
                history_parts.append(f"Bot: {content_cleaned[:300]}")
            else:
                history_parts.append(f"{msg.author.display_name}: {content_cleaned[:300]}")
    except Exception as e:
        logger.error(f"Error fetching thread history for {thread.id}: {e}")

    if not history_parts:
        return ""

    current_query_cleaned = clean_bot_mention(current_query)
    return (
        "Previous conversation in this thread:\n" +
        "\n".join(history_parts) +
        f"\n\nCurrent question from {current_author.display_name}: {current_query_cleaned}"
    )


async def _get_or_create_thread(message: discord.Message, channel: discord.TextChannel) -> discord.Thread | None:
    """If message is already in a thread, return that thread. Otherwise create a new one.
    One thread per conversation — never reuses threads by user ID. Returns None on failure."""
    if isinstance(message.channel, discord.Thread):
        thread = message.channel
        if not thread.archived and not thread.locked:
            return thread
        logger.warning(f"Thread {thread.id} is archived/locked — creating a new one")
        return None # cannot create thread from message already in a thread

    # If the message already has a thread attached to it, fetch and use it
    if message.flags.has_thread:
        try:
            thread = message.guild.get_thread(message.id) if message.guild else None
            if not thread:
                thread = await client.fetch_channel(message.id)
            if isinstance(thread, discord.Thread) and not thread.archived and not thread.locked:
                logger.info(f"Reusing existing active thread {thread.id} from message object")
                return thread
        except Exception as fetch_err:
            logger.error(f"Failed to fetch existing thread for message {message.id}: {fetch_err}")

    try:
        author = message.author
        cleaned_title = clean_bot_mention(message.content)[:50]
        thread = await message.create_thread(
            name=f"Q&A: {author.display_name} — {cleaned_title}",
            auto_archive_duration=1440,  # 24 hours
        )
        logger.info(f"Created thread {thread.id} for {author.name} — query: {cleaned_title}")
        return thread
    except discord.Forbidden:
        logger.error(f"Cannot create thread — missing permissions in channel {channel.id}")
    except discord.HTTPException as e:
        if e.code == 160004:
            logger.info(f"Thread already exists for message {message.id}. Attempting to retrieve it...")
            try:
                # Thread ID equals the message ID it was created from
                thread = message.guild.get_thread(message.id) if message.guild else None
                if not thread:
                    thread = await client.fetch_channel(message.id)
                if isinstance(thread, discord.Thread):
                    logger.info(f"Successfully retrieved existing thread {thread.id}")
                    return thread
            except Exception as fetch_err:
                logger.error(f"Failed to fetch existing thread for message {message.id}: {fetch_err}")
        else:
            logger.error(f"Discord API error creating thread: {e}")
    except Exception as e:
        logger.error(f"Unexpected error creating thread for {message.author.id}: {e}")
    return None


def is_query_covered(query: str) -> bool:
    """Check if the query contains keywords covered in .clinerules using word boundaries."""
    q = query.lower()
    
    # Predefined keyword maps based on .clinerules
    categories = {
        "setup": ["setup", "install", "run", "build", "clone", "docker", "env", "start", "dev server", "npm run dev"],
        "readme": ["readme", "read me", "documentation", "project name", "description", "user flow", "feature"],
        "contribute": ["contribute", "contributor", "fork", "pr", "pull request", "issue", "branch", "git", "onboarding"],
        "error": ["error", "exception", "bug", "fail", "crash", "issue", "logs", "broken", "debug", "not working"]
    }
    
    for cat, keywords in categories.items():
        for kw in keywords:
            # Use raw pattern and re.escape for safety, matching word boundaries for the keyword/phrase
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, q):
                return True
    return False


async def process_message(message: discord.Message):
    """Process a single message: new messages in the main channel spawn a thread,
    messages in existing threads continue the conversation there."""
    if message.author.bot:
        return

    is_in_thread = isinstance(message.channel, discord.Thread)
    is_in_configured_channel = (
        (message.channel.parent_id if is_in_thread else message.channel.id)
        == DISCORD_CHANNEL_ID_INT
    )

    bot_mentioned = (client.user in message.mentions) if client.user else False

    # Process the message if:
    # 1. It is in the configured channel (or in a thread inside it), OR
    # 2. The bot is explicitly mentioned/tagged
    if not is_in_configured_channel and not bot_mentioned:
        return

    author = message.author
    cleaned_query = clean_bot_mention(message.content)

    if is_in_thread:
        thread = message.channel
        if thread.archived or thread.locked:
            logger.warning(f"Thread {thread.id} is archived/locked — cannot respond")
            return
    else:
        channel = message.channel
        thread = await _get_or_create_thread(message, channel)
        if not thread:
            await _log_gap(cleaned_query, "thread_creation_failed")
            try:
                await message.reply(
                    "I couldn't create a thread to answer your question. Please ask a maintainer for help."
                )
            except Exception:
                pass
            return

    async with ollama_lock:
        try:
            await asyncio.sleep(1)  # let Discord register the new thread
            async with thread.typing():
                pass
        except Exception as e:
            logger.warning(f"Could not trigger typing indicator in thread {thread.id}: {e}")

        try:
            skill_context = load_skill_context()
            conversation_context = await _build_conversation_context(thread, author, cleaned_query)

            if conversation_context:
                full_prompt = conversation_context
            else:
                full_prompt = cleaned_query

            # Check if the query has sufficient information/context based on .clinerules
            if not is_query_covered(cleaned_query):
                # Pass conversation context explicitly to the LLM so it has thread history for the clarifying question
                history_str = f"Previous conversation history:\n{conversation_context}\n\n" if conversation_context else ""
                full_prompt = (
                    f"{history_str}"
                    f"The user is asking: '{cleaned_query}'. "
                    f"This query is not covered by the standard guidelines in .clinerules. "
                    f"Generate a polite response asking the user to clarify if they need help with: "
                    f"1. Setting up the project template\n"
                    f"2. Writing or updating the README\n"
                    f"3. Contributing to the repository\n"
                    f"4. Debugging an error\n"
                    f"Keep the response short, friendly, and under 5 lines."
                )
                await _log_gap(
                    cleaned_query,
                    "insufficient_info",
                    thread_id=thread.id,
                )

            response_text, used_fallback = await generate_ollama_response(full_prompt, skill_context)

            if used_fallback or not skill_context:
                await _log_gap(
                    cleaned_query,
                    "ollama_unavailable" if used_fallback else "no_skill_context",
                    thread_id=thread.id,
                )
        except Exception as e:
            logger.error(f"Unexpected error processing message from {author.name}: {e}")
            response_text = "An unexpected error occurred. Please try again or ask a maintainer."
            await _log_gap(cleaned_query, f"processing_error: {e}", thread_id=thread.id)

        if len(response_text) > 1900:
            response_text = response_text[:1896] + "..."

        try:
            await thread.send(response_text)
        except discord.Forbidden:
            logger.error(f"Cannot send message to thread {thread.id}")
        except discord.HTTPException as e:
            logger.error(f"Error sending to thread {thread.id}: {e}")


async def wait_for_ollama():
    """Wait until Ollama is up and responding."""
    logger.info("Waiting for Ollama to be ready...")
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http_client:
                response = await http_client.get("http://localhost:11434/")
                if response.status_code == 200:
                    logger.info("Ollama is ready!")
                    return
        except httpx.RequestError:
            pass
        logger.info("Ollama not reachable yet. Retrying in 10 seconds...")
        await asyncio.sleep(10)


@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user.name} ({client.user.id})")

    # Wait for Ollama to be ready before processing the backlog
    await wait_for_ollama()

    logger.info("Checking for missed messages...")

    try:
        channel = await client.fetch_channel(DISCORD_CHANNEL_ID_INT)

        # Find the last message sent by the bot
        last_bot_msg = None
        async for msg in channel.history(limit=50):
            if msg.author.id == client.user.id:
                last_bot_msg = msg
                break

        messages_to_process = []
        if last_bot_msg:
            async for msg in channel.history(after=last_bot_msg, oldest_first=True):
                if not msg.author.bot:
                    messages_to_process.append(msg)
        else:
            async for msg in channel.history(limit=5, oldest_first=True):
                if not msg.author.bot:
                    messages_to_process.append(msg)

        logger.info(f"Found {len(messages_to_process)} missed messages. Processing...")
        for msg in messages_to_process:
            await process_message(msg)

    except Exception as e:
        logger.error(f"Error fetching missed messages: {e}")

    logger.info("AOSSIE Contributor Assistant MVP is fully ready.")


@client.event
async def on_message(message: discord.Message):
    await process_message(message)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN is missing from environment. Exiting.")
        exit(1)

    if not DISCORD_CHANNEL_ID:
        logger.critical("DISCORD_CHANNEL_ID is missing from environment. Exiting.")
        exit(1)

    try:
        DISCORD_CHANNEL_ID_INT = int(DISCORD_CHANNEL_ID)
    except ValueError:
        logger.critical(
            f"DISCORD_CHANNEL_ID '{DISCORD_CHANNEL_ID}' is not a valid integer. Exiting."
        )
        exit(1)

    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)
