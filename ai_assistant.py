#!/usr/bin/env python3
"""
AI Assistant for Telegram Message Monitor
Provides auto-suggestions, Q&A, and guided responses using Claude API or local LLM.
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional, List, Dict, Any

import anthropic
from openai import OpenAI

import config
import database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API clients
anthropic_client = None
local_llm_client = None

# Current provider: 'anthropic', 'local', 'cli', or 'cli_token'
# Will be loaded from database on startup
current_provider = 'local'
use_tailscale_setting = True  # Whether to use tailscale for local provider

# Default context window size
DEFAULT_CONTEXT_MESSAGES = 50
MAX_CONTEXT_MESSAGES = 10000  # Allow large context for LLMs with big context windows

# Default prompts to seed the database
DEFAULT_PROMPTS = [
    {
        "name": "Balanced",
        "description": "Thoughtful, warm responses that match her energy",
        "system_prompt": """You are helping craft replies in a personal conversation.

Your role is to suggest 3 reply options that are:
- Natural and conversational
- Match the energy and tone of the conversation
- Thoughtful but not overthinking
- Authentic, not manipulative

Analyze the conversation context and her latest message, then provide:
1. A SHORT reply (1-2 sentences, casual)
2. A MEDIUM reply (2-3 sentences, engaged)
3. A LONGER reply (3-4 sentences, deeper connection)

Format your response as JSON:
{
    "analysis": "Brief analysis of her message and emotional state",
    "suggestions": [
        {"type": "short", "text": "..."},
        {"type": "medium", "text": "..."},
        {"type": "longer", "text": "..."}
    ]
}""",
        "is_default": True
    },
    {
        "name": "Playful",
        "description": "Light, fun, teasing responses",
        "system_prompt": """You are helping craft playful, fun replies in a personal conversation.

Your role is to suggest 3 reply options that are:
- Light-hearted and fun
- Playfully teasing when appropriate
- Confident but not arrogant
- Create positive energy

Provide:
1. A WITTY reply (clever, light humor)
2. A TEASING reply (playful challenge)
3. A CHARMING reply (warm with personality)

Format your response as JSON:
{
    "analysis": "Brief analysis of the vibe and opportunity for playfulness",
    "suggestions": [
        {"type": "witty", "text": "..."},
        {"type": "teasing", "text": "..."},
        {"type": "charming", "text": "..."}
    ]
}"""
    },
    {
        "name": "Deep",
        "description": "Thoughtful, meaningful responses for deeper conversations",
        "system_prompt": """You are helping craft meaningful replies in a personal conversation.

Your role is to suggest 3 reply options that are:
- Thoughtful and genuine
- Show emotional intelligence
- Create deeper connection
- Vulnerable when appropriate

Provide:
1. An EMPATHETIC reply (understanding her feelings)
2. A SHARING reply (opening up about yourself)
3. A CURIOUS reply (deepening the conversation with questions)

Format your response as JSON:
{
    "analysis": "Analysis of the emotional undertones and connection opportunity",
    "suggestions": [
        {"type": "empathetic", "text": "..."},
        {"type": "sharing", "text": "..."},
        {"type": "curious", "text": "..."}
    ]
}"""
    },
    {
        "name": "Direct",
        "description": "Clear, confident, no-nonsense responses",
        "system_prompt": """You are helping craft direct, confident replies in a personal conversation.

Your role is to suggest 3 reply options that are:
- Clear and straightforward
- Confident without being aggressive
- Respect boundaries
- Get to the point

Provide:
1. A BRIEF reply (minimal, confident)
2. A CLEAR reply (straightforward, no ambiguity)
3. An ASSERTIVE reply (sets tone/expectation)

Format your response as JSON:
{
    "analysis": "What needs to be communicated clearly",
    "suggestions": [
        {"type": "brief", "text": "..."},
        {"type": "clear", "text": "..."},
        {"type": "assertive", "text": "..."}
    ]
}"""
    }
]


def init_anthropic_client():
    """Initialize the Anthropic client."""
    global anthropic_client
    api_key = os.getenv("ANTHROPIC_API_KEY") or getattr(config, "ANTHROPIC_API_KEY", None)
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not found.")
        return False
    anthropic_client = anthropic.Anthropic(api_key=api_key)
    return True


def init_local_llm_client(use_tailscale=False):
    """Initialize the local LLM client (OpenAI-compatible)."""
    global local_llm_client
    if use_tailscale:
        # Check both config attribute and environment variable
        base_url = getattr(config, "LOCAL_LLM_TAILSCALE_URL", None)
        if not base_url:
            base_url = os.environ.get("LOCAL_LLM_TAILSCALE_URL", "http://100.114.20.108:1234/v1")
    else:
        base_url = getattr(config, "LOCAL_LLM_URL", "http://localhost:1234/v1")
    logger.info(f"Initializing local LLM client at: {base_url}")
    local_llm_client = OpenAI(base_url=base_url, api_key="lm-studio")
    return True


def check_local_llm_available(use_tailscale=False):
    """Check if the local LLM server is available."""
    try:
        if use_tailscale:
            # Check both config attribute and environment variable
            url = getattr(config, "LOCAL_LLM_TAILSCALE_URL", None)
            if not url:
                url = os.environ.get("LOCAL_LLM_TAILSCALE_URL", "http://100.114.20.108:1234/v1")
            logger.info(f"Tailscale URL from config: {url}")
        else:
            url = getattr(config, "LOCAL_LLM_URL", "http://localhost:1234/v1")

        logger.info(f"Checking LLM availability at: {url}/models")
        # Use verify=True for HTTPS (Tailscale certs are valid)
        response = requests.get(f"{url}/models", timeout=10)
        logger.info(f"LLM check response: {response.status_code}")
        return response.status_code == 200
    except requests.exceptions.SSLError as e:
        logger.warning(f"SSL error for {'tailscale' if use_tailscale else 'localhost'}: {e}")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Connection error for {'tailscale' if use_tailscale else 'localhost'}: {e}")
        return False
    except requests.exceptions.Timeout as e:
        logger.warning(f"Timeout for {'tailscale' if use_tailscale else 'localhost'}: {e}")
        return False
    except Exception as e:
        logger.warning(f"LLM check failed for {'tailscale' if use_tailscale else 'localhost'}: {type(e).__name__}: {e}")
        return False


def check_cli_available() -> bool:
    """Check if Claude CLI is available."""
    import subprocess
    try:
        result = subprocess.run(['claude', '--version'], capture_output=True, timeout=5)
        return result.returncode == 0
    except:
        return False


def check_cli_token_available() -> bool:
    """Check if Claude CLI Token (OAuth) is configured."""
    oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', '')
    return bool(oauth_token) and check_cli_available()


def call_claude_cli(prompt: str, system_prompt: str = None, model: str = 'haiku') -> str:
    """Call Claude CLI and return the response text.

    For cli_token mode, uses OAuth token (Max membership) instead of API credits.
    """
    import subprocess

    # Build command - pass prompt via stdin instead of -p to avoid shell parsing issues
    cmd = ['claude', '--model', model, '--output-format', 'text']

    # For cli_token mode, ensure OAuth token is set and ALL API keys are removed
    if current_provider == 'cli_token':
        oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', '')
        if not oauth_token:
            raise Exception("CLAUDE_CODE_OAUTH_TOKEN not set. Run: claude setup-token")
        os.environ['CLAUDE_CODE_OAUTH_TOKEN'] = oauth_token

        # Save and remove all potential API key env vars
        saved_env_vars = {}
        api_key_vars = ['ANTHROPIC_API_KEY', 'CLAUDE_API_KEY', 'ANTHROPIC_AUTH_TOKEN']
        for var in api_key_vars:
            if var in os.environ:
                saved_env_vars[var] = os.environ.pop(var)

        # Build a clean environment with only OAuth token, no API keys
        clean_env = os.environ.copy()
        for key in api_key_vars:
            clean_env.pop(key, None)
    else:
        saved_env_vars = {}
        clean_env = None  # Use default environment

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            env=clean_env  # Use clean environment for cli_token mode
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            # Check for API credit errors - this means OAuth isn't being used properly
            if current_provider == 'cli_token' and ('credit balance' in error_msg.lower() or 'api key' in error_msg.lower()):
                raise Exception(
                    "CLI is still using API mode instead of OAuth. "
                    "Check Claude CLI configuration. "
                    "Try running 'claude /logout' then 'claude /login' on the server."
                )
            raise Exception(f"CLI failed: {error_msg}")

        return result.stdout.strip()
    finally:
        # Restore saved environment variables
        for var, value in saved_env_vars.items():
            os.environ[var] = value


def set_provider(provider: str, use_tailscale: bool = False) -> Dict[str, Any]:
    """Set the AI provider ('anthropic', 'local', 'cli', or 'cli_token').

    Persists the selection to database for resilience across restarts.
    """
    global current_provider, use_tailscale_setting
    valid_providers = ('anthropic', 'local', 'cli', 'cli_token')
    if provider not in valid_providers:
        return {"error": f"Unknown provider: {provider}. Valid: {valid_providers}"}

    if provider == 'local':
        if not check_local_llm_available(use_tailscale):
            # Get the URL that was tried for better error message
            if use_tailscale:
                url = getattr(config, "LOCAL_LLM_TAILSCALE_URL", None) or os.environ.get("LOCAL_LLM_TAILSCALE_URL", "not set")
                return {"error": f"Cannot connect to Tailscale LLM at: {url}", "available": False}
            else:
                url = getattr(config, "LOCAL_LLM_URL", "http://localhost:1234/v1")
                return {"error": f"Cannot connect to local LLM at: {url}", "available": False}
        init_local_llm_client(use_tailscale)
    elif provider == 'cli':
        if not check_cli_available():
            return {"error": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"}
    elif provider == 'cli_token':
        if not check_cli_token_available():
            return {"error": "CLI Token not configured. Set CLAUDE_CODE_OAUTH_TOKEN env var"}

    current_provider = provider
    use_tailscale_setting = use_tailscale

    # Persist to database
    try:
        database.update_ai_settings(provider=provider, use_tailscale=1 if use_tailscale else 0)
        logger.info(f"AI provider set and persisted to: {provider}{' (tailscale)' if use_tailscale else ''}")
    except Exception as e:
        logger.warning(f"Could not persist AI settings to database: {e}")

    return {"success": True, "provider": provider}


def get_provider_status() -> Dict[str, Any]:
    """Get status of all AI providers.

    Returns the current provider setting (from database) and availability of all providers.
    """
    anthropic_ok = bool(os.getenv("ANTHROPIC_API_KEY") or getattr(config, "ANTHROPIC_API_KEY", None))
    local_ok = check_local_llm_available(use_tailscale=False)
    local_tailscale_ok = check_local_llm_available(use_tailscale=True)
    cli_ok = check_cli_available()
    cli_token_ok = check_cli_token_available()

    # Return current provider with tailscale flag so frontend can set correct dropdown value
    current_with_tailscale = current_provider
    if current_provider == 'local' and use_tailscale_setting:
        current_with_tailscale = 'local_tailscale'

    return {
        "current": current_with_tailscale,
        "use_tailscale": use_tailscale_setting,
        "anthropic": {"available": anthropic_ok, "name": "Claude API"},
        "local": {"available": local_ok, "name": "Local LLM (localhost)"},
        "local_tailscale": {"available": local_tailscale_ok, "name": "Local LLM (Tailscale)"},
        "cli": {"available": cli_ok, "name": "Claude CLI (Local)"},
        "cli_token": {"available": cli_token_ok, "name": "Claude CLI Token (Render)"}
    }


def init_client():
    """Initialize the default client (for backwards compatibility)."""
    return init_anthropic_client()


def ensure_default_prompts():
    """Ensure default prompts exist in the database."""
    existing = database.get_ai_prompts(active_only=False)
    if not existing:
        logger.info("Creating default AI prompts...")
        for prompt in DEFAULT_PROMPTS:
            database.save_ai_prompt(
                name=prompt["name"],
                system_prompt=prompt["system_prompt"],
                description=prompt.get("description"),
                is_default=prompt.get("is_default", False)
            )
        logger.info(f"Created {len(DEFAULT_PROMPTS)} default prompts")


def build_context(
    limit: int = DEFAULT_CONTEXT_MESSAGES,
    days: int = None,
    include_summary: bool = True
) -> str:
    """
    Build conversation context string from messages and summaries.

    Args:
        limit: Number of messages to include (if days is None)
        days: Number of days of history to include (overrides limit if set)
        include_summary: Whether to include the latest summary
    """
    parts = []

    # Add latest summary if available
    if include_summary:
        summary = database.get_latest_summary()
        if summary:
            parts.append(f"=== CONVERSATION SUMMARY (up to {summary['end_date']}) ===")
            parts.append(summary['summary'])
            if summary.get('key_facts'):
                parts.append(f"\nKey facts: {summary['key_facts']}")
            parts.append("=== END SUMMARY ===\n")

    # Add recent messages - by days or by count
    if days is not None:
        messages = database.get_context_messages_by_days(days=days)
    else:
        messages = database.get_context_messages(limit=limit)

    if messages:
        parts.append("=== RECENT MESSAGES ===")
        my_name = getattr(config, 'MY_NAME', 'Me')
        for msg in messages:
            sender = "Me" if msg['sender_name'] == my_name else "Her"
            timestamp = msg['timestamp'][:16] if msg['timestamp'] else ''
            text = msg['text'] or f"[{msg.get('media_type', 'media')}]"
            parts.append(f"[{timestamp}] {sender}: {text}")
        parts.append("=== END MESSAGES ===")

    return "\n".join(parts)


def generate_suggestions(
    message_text: str,
    message_id: int,
    prompt_id: Optional[int] = None,
    custom_prompt: Optional[str] = None,
    context_limit: int = DEFAULT_CONTEXT_MESSAGES,
    context_days: int = None,
    num_suggestions: int = 3
) -> Dict[str, Any]:
    """Generate reply suggestions for a message.

    Args:
        message_text: The message text to generate suggestions for
        message_id: ID of the message
        prompt_id: Optional prompt ID to use
        custom_prompt: Optional custom system prompt
        context_limit: Number of messages to include as context (if context_days is None)
        context_days: Number of days of history to use (overrides context_limit if set)
        num_suggestions: Number of suggestions to generate
    """
    global anthropic_client, local_llm_client

    # Use custom prompt if provided (one-time use), otherwise get from DB
    if custom_prompt:
        logger.info(f"Using custom prompt ({len(custom_prompt)} chars)")
        prompt = {'id': None, 'name': 'Custom (one-time)', 'system_prompt': custom_prompt}
    elif prompt_id:
        logger.info(f"Using prompt_id: {prompt_id}")
        prompt = database.get_ai_prompt(prompt_id)
    else:
        logger.info("Using default prompt")
        prompt = database.get_default_prompt()

    if not prompt:
        ensure_default_prompts()
        prompt = database.get_default_prompt()

    if not prompt:
        return {"error": "No AI prompt configured"}

    # Log which system prompt is being used
    logger.info(f"System prompt preview: {prompt['system_prompt'][:100]}...")

    # Build context - use days if specified, otherwise use message limit
    if context_days:
        logger.info(f"Building context with {context_days} days of history")
        context = build_context(days=context_days, include_summary=True)
    else:
        logger.info(f"Building context with {context_limit} messages")
        context = build_context(limit=context_limit, include_summary=True)

    # Create format instructions that work well with local LLMs
    format_instructions = f"""
IMPORTANT: Output EXACTLY {num_suggestions} reply options in this EXACT format:

---ANALYSIS---
[Your brief analysis here - 1-2 sentences max]

---REPLY 1---
[First reply option - the actual message text only, nothing else]

---REPLY 2---
[Second reply option - the actual message text only, nothing else]

---REPLY 3---
[Third reply option - the actual message text only, nothing else]
""" if num_suggestions == 3 else f"""
IMPORTANT: Output EXACTLY {num_suggestions} reply options in this EXACT format:

---ANALYSIS---
[Your brief analysis here - 1-2 sentences max]

""" + "\n".join([f"---REPLY {i+1}---\n[Reply option {i+1} - the actual message text only]" for i in range(num_suggestions)])

    # Create the user message
    user_message = f"""Here is the conversation context:

{context}

Her latest message that needs a reply:
"{message_text}"

{format_instructions}

Remember: Each reply should be ONLY the message text I would send - no labels, no quotes, no explanations."""

    try:
        if current_provider in ('cli', 'cli_token'):
            # Use Claude CLI - include explicit framing to override Claude Code's default behavior
            cli_preamble = """CONTEXT: This is a personal dashboard tool I built for myself to help brainstorm message ideas.
I will review, modify, and decide what to actually send. You're helping me think through options, not writing messages for me.
This is no different than asking a friend "what should I say?" - I'm using you as a sounding board.

TASK: Help me brainstorm reply ideas based on the conversation below. I'll pick and modify what resonates with me.

"""
            full_prompt = f"""{cli_preamble}{prompt['system_prompt']}

{user_message}"""
            response_text = call_claude_cli(full_prompt, model='haiku')
            tokens_used = 0  # CLI doesn't report tokens
        elif current_provider == 'local' and local_llm_client:
            # Use local LLM
            model = getattr(config, "LOCAL_LLM_MODEL", "tensorblock/Qwen2.5-Coder-32B-Instruct-GGUF")
            response = local_llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt['system_prompt']},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=1024
            )
            response_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
        else:
            # Use Anthropic API
            if not anthropic_client:
                if not init_anthropic_client():
                    return {"error": "AI not configured - missing ANTHROPIC_API_KEY"}
            response = anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1024,
                system=prompt['system_prompt'],
                messages=[{"role": "user", "content": user_message}]
            )
            response_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

        # Try to parse as JSON
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response_text[json_start:json_end])
            else:
                result = {"raw_response": response_text}
        except json.JSONDecodeError:
            result = {"raw_response": response_text}

        # Save to database
        database.save_ai_suggestion(
            message_id=message_id,
            prompt_id=prompt['id'],
            suggestions=json.dumps(result),
            context_used=f"{context_days} days" if context_days else f"{context_limit} messages",
            tokens_used=tokens_used
        )

        result['tokens_used'] = tokens_used
        result['prompt_name'] = prompt['name']
        result['provider'] = current_provider
        return result

    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        return {"error": str(e)}


def ask_question(
    question: str,
    context_limit: int = DEFAULT_CONTEXT_MESSAGES,
    context_days: int = None
) -> Dict[str, Any]:
    """
    Ask a question about the conversation.

    Args:
        question: The question to ask
        context_limit: Number of messages to use as context (if context_days is None)
        context_days: Number of days of history to use (overrides context_limit if set)
    """
    global anthropic_client, local_llm_client

    # Build context - days takes precedence over limit
    context = build_context(limit=context_limit, days=context_days, include_summary=True)

    # Get conversation history for continuity
    conv_history = database.get_ai_conversation(limit=10)

    # Build messages array
    messages = []
    for msg in conv_history:
        messages.append({"role": msg['role'], "content": msg['content']})

    # Add current question
    user_message = f"""Based on this conversation context:

{context}

Question: {question}"""

    messages.append({"role": "user", "content": user_message})

    system_prompt = """You are an AI assistant helping analyze a personal conversation between two people.
You have access to their message history and can answer questions about:
- Patterns in their communication
- Emotional dynamics
- What topics they discuss
- Timing and frequency of messages
- Any insights about the relationship

Be helpful, insightful, and respectful of privacy. Give specific examples from the messages when relevant."""

    try:
        if current_provider in ('cli', 'cli_token'):
            # Use Claude CLI - include explicit framing
            cli_preamble = """CONTEXT: This is my personal dashboard tool for analyzing my own conversation history.
I'm asking you to help me understand patterns, dynamics, and insights from messages I've exchanged.
This is for personal reflection and self-improvement.

"""
            # Build conversation context for CLI
            conv_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])
            full_prompt = f"""{cli_preamble}{system_prompt}

{conv_text}"""
            try:
                response_text = call_claude_cli(full_prompt, model='sonnet')
                tokens_used = 0
            except Exception as cli_error:
                logger.error(f"CLI error in Q&A: {type(cli_error).__name__}: {cli_error}")
                return {"error": f"CLI error: {str(cli_error)}"}
        elif current_provider == 'local':
            # Use local LLM
            if not local_llm_client:
                return {"error": "Local LLM not initialized. Select a different provider or check LLM server."}
            model = getattr(config, "LOCAL_LLM_MODEL", "tensorblock/Qwen2.5-Coder-32B-Instruct-GGUF")
            all_messages = [{"role": "system", "content": system_prompt}] + messages
            try:
                response = local_llm_client.chat.completions.create(
                    model=model,
                    messages=all_messages,
                    temperature=0.7,
                    max_tokens=2048
                )
                response_text = response.choices[0].message.content
                tokens_used = response.usage.total_tokens if response.usage else 0
            except Exception as llm_error:
                logger.error(f"Local LLM error: {type(llm_error).__name__}: {llm_error}")
                return {"error": f"Local LLM error: {str(llm_error)}"}
        else:
            # Use Anthropic API
            if not anthropic_client:
                if not init_anthropic_client():
                    return {"error": "AI not configured - missing ANTHROPIC_API_KEY"}
            response = anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2048,
                system=system_prompt,
                messages=messages
            )
            response_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

        # Save to conversation history
        database.save_ai_conversation("user", question, tokens_used=0)
        database.save_ai_conversation("assistant", response_text, tokens_used=tokens_used)

        return {
            "answer": response_text,
            "tokens_used": tokens_used,
            "provider": current_provider
        }

    except Exception as e:
        logger.error(f"Error in Q&A: {e}")
        return {"error": str(e)}


def generate_summary(days: int = 7) -> Dict[str, Any]:
    """Generate a summary of recent conversation."""
    global anthropic_client, local_llm_client

    # Get messages from the period
    messages = database.get_context_messages(limit=MAX_CONTEXT_MESSAGES)
    if not messages:
        return {"error": "No messages to summarize"}

    # Build message text
    my_name = getattr(config, 'MY_NAME', 'Me')
    message_text = []
    for msg in messages:
        sender = "Me" if msg['sender_name'] == my_name else "Her"
        text = msg['text'] or f"[{msg.get('media_type', 'media')}]"
        message_text.append(f"{sender}: {text}")

    start_date = messages[0]['timestamp'][:10] if messages else ''
    end_date = messages[-1]['timestamp'][:10] if messages else ''

    system_prompt = """Summarize this conversation between two people. Include:
1. Main topics discussed
2. Emotional tone and dynamics
3. Key moments or important exchanges
4. Any patterns you notice

Also extract key facts as a comma-separated list (names mentioned, places, events, preferences, etc.)

Format your response as JSON:
{
    "summary": "...",
    "key_facts": "fact1, fact2, fact3..."
}"""

    user_message = f"""Summarize these {len(messages)} messages:

{chr(10).join(message_text)}"""

    try:
        if current_provider in ('cli', 'cli_token'):
            # Use Claude CLI - include explicit framing
            cli_preamble = """CONTEXT: This is my personal dashboard tool for summarizing my own conversation history.
I want to keep track of key topics and facts from my conversations for my own reference.

"""
            full_prompt = f"""{cli_preamble}{system_prompt}

{user_message}"""
            response_text = call_claude_cli(full_prompt, model='haiku')
            tokens_used = 0
        elif current_provider == 'local' and local_llm_client:
            # Use local LLM
            model = getattr(config, "LOCAL_LLM_MODEL", "tensorblock/Qwen2.5-Coder-32B-Instruct-GGUF")
            response = local_llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=1024
            )
            response_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
        else:
            # Use Anthropic API
            if not anthropic_client:
                if not init_anthropic_client():
                    return {"error": "AI not configured - missing ANTHROPIC_API_KEY"}
            response = anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            response_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

        # Parse response
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response_text[json_start:json_end])
            else:
                result = {"summary": response_text, "key_facts": ""}
        except json.JSONDecodeError:
            result = {"summary": response_text, "key_facts": ""}

        # Save summary
        database.save_conversation_summary(
            summary=result.get('summary', response_text),
            messages_covered=len(messages),
            start_date=start_date,
            end_date=end_date,
            key_facts=result.get('key_facts', '')
        )

        result['tokens_used'] = tokens_used
        result['messages_covered'] = len(messages)
        result['provider'] = current_provider
        return result

    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return {"error": str(e)}


def process_pending_messages() -> List[Dict[str, Any]]:
    """Process messages that don't have suggestions yet."""
    results = []

    # Get messages without suggestions
    pending = database.get_messages_without_suggestions(limit=5)

    for msg in pending:
        if msg.get('text'):
            logger.info(f"Generating suggestions for message {msg['message_id']}")
            result = generate_suggestions(
                message_text=msg['text'],
                message_id=msg['message_id']
            )
            result['message_id'] = msg['message_id']
            results.append(result)

    return results


def load_settings_from_database():
    """Load AI settings from database on startup."""
    global current_provider, use_tailscale_setting, local_llm_client
    try:
        settings = database.get_ai_settings()
        provider = settings.get('provider', 'local')
        use_tailscale = bool(settings.get('use_tailscale', 1))

        logger.info(f"Loading AI settings from database: provider={provider}, use_tailscale={use_tailscale}")

        # Set provider without validation (just set the globals)
        current_provider = provider
        use_tailscale_setting = use_tailscale

        # Initialize the appropriate client
        if provider == 'local':
            if check_local_llm_available(use_tailscale):
                init_local_llm_client(use_tailscale)
                logger.info(f"Local LLM client initialized (tailscale={use_tailscale})")
            else:
                logger.warning(f"Local LLM not available (tailscale={use_tailscale}), provider set but not connected")
        elif provider == 'anthropic':
            init_anthropic_client()
        # cli and cli_token don't need client initialization

    except Exception as e:
        logger.warning(f"Could not load AI settings from database: {e}, using defaults")
        current_provider = 'local'
        use_tailscale_setting = True


# Initialize on import
init_client()
ensure_default_prompts()
load_settings_from_database()
