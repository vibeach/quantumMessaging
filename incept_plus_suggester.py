"""
Incept+ Suggestion Generator
Uses Claude API or CLI to generate intelligent improvement suggestions for the codebase.
Supports modes: api, cli, cli_token (default: cli)
"""

import os
import json
import subprocess
import anthropic
from datetime import datetime
import config
import database

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_suggestions(direction, context=None, max_suggestions=10):
    """
    Generate improvement suggestions based on the given direction.

    Args:
        direction: Description of what improvements to focus on (e.g., "make UI more responsive")
        context: Optional additional context about the codebase
        max_suggestions: Maximum number of suggestions to generate

    Returns:
        List of suggestion dictionaries with title, description, implementation_details, etc.
    """

    # Get settings
    settings = database.get_incept_plus_settings()
    mode = settings.get('suggestion_mode', 'cli')
    model = settings.get('suggestion_model', 'claude-sonnet-4-20250514')

    # Route to appropriate handler based on mode
    if mode == 'api':
        return generate_suggestions_api(direction, context, max_suggestions, model)
    elif mode == 'cli_token':
        return generate_suggestions_cli_token(direction, context, max_suggestions, model)
    else:  # 'cli' or any other
        return generate_suggestions_cli(direction, context, max_suggestions, model)


def generate_suggestions_api(direction, context=None, max_suggestions=10, model='claude-sonnet-4-20250514'):
    """Generate suggestions using Claude API."""

    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build system prompt
    system_prompt = """You are an expert software architect and developer. Your task is to analyze a codebase and suggest concrete, actionable improvements.

For each suggestion, provide:
1. A clear, concise title (5-10 words)
2. A detailed description explaining why this improvement is valuable
3. Specific implementation details including:
   - Which files need to be modified or created
   - Key code changes required
   - Any dependencies or prerequisites
4. Category (feature, bugfix, performance, refactoring, ui, testing, documentation, security)
5. Priority (1=critical, 2=high, 3=medium, 4=low, 5=nice-to-have)
6. Estimated effort (small, medium, large)
7. Dependencies on other changes

Be specific and practical. Focus on improvements that add real value.
Return your response as a JSON array of suggestions."""

    # Build user prompt
    user_prompt = f"""I'm working on a Telegram monitoring dashboard application. Here's what I want to improve:

Direction: {direction}

"""

    if context:
        user_prompt += f"""Additional Context:
{context}

"""

    user_prompt += f"""Please suggest {max_suggestions} specific improvements that align with this direction.

Current codebase features:
- Flask web application with Jinja2 templates
- SQLite database for storing messages and metadata
- Telegram client integration for monitoring
- Claude AI integration for automated code changes (Incept system)
- AI assistant for message suggestions
- Media processing and transcription
- Dark/light theme support

Return a JSON array with this structure:
[
  {{
    "title": "Short descriptive title",
    "description": "Detailed explanation of the improvement and its value",
    "implementation_details": "Step-by-step implementation guide with specific file paths and code changes",
    "category": "feature|bugfix|performance|refactoring|ui|testing|documentation|security",
    "priority": 1-5,
    "estimated_effort": "small|medium|large",
    "dependencies": "Any prerequisites or related changes needed, or null"
  }}
]"""

    try:
        # Call Claude API
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # Extract suggestions from response
        content = response.content[0].text

        # Try to parse JSON from the response
        # Sometimes Claude wraps JSON in markdown code blocks
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            content = content[json_start:json_end].strip()
        elif "```" in content:
            json_start = content.find("```") + 3
            json_end = content.find("```", json_start)
            content = content[json_start:json_end].strip()

        suggestions = json.loads(content)

        # Validate and normalize suggestions
        normalized_suggestions = []
        for i, sug in enumerate(suggestions[:max_suggestions]):
            normalized_suggestions.append({
                'title': sug.get('title', f'Improvement #{i+1}'),
                'description': sug.get('description', ''),
                'implementation_details': sug.get('implementation_details', ''),
                'category': sug.get('category', 'feature'),
                'priority': int(sug.get('priority', 3)),
                'estimated_effort': sug.get('estimated_effort', 'medium'),
                'dependencies': sug.get('dependencies'),
                'context': direction
            })

        return normalized_suggestions

    except json.JSONDecodeError as e:
        # If JSON parsing fails, return a fallback suggestion with the raw response
        return [{
            'title': 'Claude Response (Parse Error)',
            'description': f'Failed to parse suggestions. Raw response: {content[:500]}...',
            'implementation_details': 'Manual review required',
            'category': 'feature',
            'priority': 3,
            'estimated_effort': 'unknown',
            'dependencies': None,
            'context': direction
        }]
    except Exception as e:
        raise Exception(f"Failed to generate suggestions: {str(e)}")


def build_suggestion_prompt(direction, context=None, max_suggestions=10):
    """Build the prompt for generating suggestions (shared by CLI modes)."""
    prompt = f"""You are an expert software architect. Analyze the codebase and suggest {max_suggestions} improvements.

DIRECTION: {direction}
"""
    if context:
        prompt += f"\nCONTEXT: {context}\n"

    prompt += """
Current codebase features:
- Flask web application with Jinja2 templates
- SQLite database for messages/metadata
- Telegram client integration
- Claude AI for automated code changes (Incept)
- Media processing and transcription
- Dark/light theme support

Return ONLY a valid JSON array (no markdown, no explanation) with this structure:
[
  {
    "title": "Short title (5-10 words)",
    "description": "Why this improvement is valuable",
    "implementation_details": "Step-by-step guide with file paths",
    "category": "feature|bugfix|performance|refactoring|ui|testing|documentation|security",
    "priority": 1-5,
    "estimated_effort": "small|medium|large",
    "dependencies": "Prerequisites or null"
  }
]"""
    return prompt


def parse_suggestions_response(content, direction, max_suggestions):
    """Parse JSON suggestions from response content."""
    # Try to extract JSON from response
    if "```json" in content:
        json_start = content.find("```json") + 7
        json_end = content.find("```", json_start)
        content = content[json_start:json_end].strip()
    elif "```" in content:
        json_start = content.find("```") + 3
        json_end = content.find("```", json_start)
        content = content[json_start:json_end].strip()

    # Find JSON array in content
    if '[' in content:
        start = content.find('[')
        end = content.rfind(']') + 1
        content = content[start:end]

    try:
        suggestions = json.loads(content)

        # Validate and normalize suggestions
        normalized = []
        for i, sug in enumerate(suggestions[:max_suggestions]):
            normalized.append({
                'title': sug.get('title', f'Improvement #{i+1}'),
                'description': sug.get('description', ''),
                'implementation_details': sug.get('implementation_details', ''),
                'category': sug.get('category', 'feature'),
                'priority': int(sug.get('priority', 3)),
                'estimated_effort': sug.get('estimated_effort', 'medium'),
                'dependencies': sug.get('dependencies'),
                'context': direction
            })
        return normalized

    except json.JSONDecodeError:
        return [{
            'title': 'Parse Error',
            'description': f'Failed to parse: {content[:500]}...',
            'implementation_details': 'Manual review required',
            'category': 'feature',
            'priority': 3,
            'estimated_effort': 'unknown',
            'dependencies': None,
            'context': direction
        }]


def generate_suggestions_cli(direction, context=None, max_suggestions=10, model='claude-sonnet-4-20250514'):
    """Generate suggestions using local Claude CLI."""

    # Map API model names to CLI model names
    model_map = {
        'claude-sonnet-4-20250514': 'sonnet',
        'claude-opus-4-20250514': 'opus',
        'claude-3-5-sonnet-20241022': 'sonnet',
        'claude-3-5-haiku-20241022': 'haiku',
    }
    cli_model = model_map.get(model, 'sonnet')

    prompt = build_suggestion_prompt(direction, context, max_suggestions)

    try:
        # Run Claude CLI
        # Pass prompt via stdin instead of -p to avoid shell parsing issues
        result = subprocess.run(
            ['claude', '--model', cli_model, '--output-format', 'text'],
            cwd=PROJECT_DIR,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode != 0:
            raise Exception(f"CLI failed: {result.stderr}")

        return parse_suggestions_response(result.stdout, direction, max_suggestions)

    except subprocess.TimeoutExpired:
        raise Exception("Claude CLI timed out after 5 minutes")
    except FileNotFoundError:
        raise Exception("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")
    except Exception as e:
        raise Exception(f"CLI error: {str(e)}")


def generate_suggestions_cli_token(direction, context=None, max_suggestions=10, model='claude-sonnet-4-20250514'):
    """Generate suggestions using Claude CLI with OAuth token (for Render/headless).

    This uses your Max membership (unlimited usage) instead of API credits.
    The OAuth token is obtained by running 'claude setup-token' locally.

    IMPORTANT: We must ensure NO API key is accessible to the CLI, otherwise
    it will prefer API mode over OAuth.
    """

    # Check for OAuth token
    oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', '')
    if not oauth_token:
        raise Exception("CLAUDE_CODE_OAUTH_TOKEN not set. Run: claude setup-token")

    # Save any API keys so we can restore them after
    saved_env_vars = {}
    api_key_vars = [
        'ANTHROPIC_API_KEY',
        'CLAUDE_API_KEY',
        'ANTHROPIC_AUTH_TOKEN',
    ]

    for var in api_key_vars:
        if var in os.environ:
            saved_env_vars[var] = os.environ.pop(var)

    # Ensure the OAuth token is set in environment
    os.environ['CLAUDE_CODE_OAUTH_TOKEN'] = oauth_token

    try:
        # Use dedicated OAuth CLI function
        return generate_suggestions_cli_oauth(direction, context, max_suggestions, model)
    finally:
        # Restore saved environment variables for other modes
        for var, value in saved_env_vars.items():
            os.environ[var] = value


def generate_suggestions_cli_oauth(direction, context=None, max_suggestions=10, model='claude-sonnet-4-20250514'):
    """Generate suggestions using Claude CLI specifically with OAuth authentication."""

    # Map API model names to CLI model names
    model_map = {
        'claude-sonnet-4-20250514': 'sonnet',
        'claude-opus-4-20250514': 'opus',
        'claude-3-5-sonnet-20241022': 'sonnet',
        'claude-3-5-haiku-20241022': 'haiku',
    }
    cli_model = model_map.get(model, 'sonnet')

    prompt = build_suggestion_prompt(direction, context, max_suggestions)

    try:
        # Build a clean environment with only OAuth token, no API keys
        clean_env = os.environ.copy()
        # Double-check no API keys are present
        for key in ['ANTHROPIC_API_KEY', 'CLAUDE_API_KEY', 'ANTHROPIC_AUTH_TOKEN']:
            clean_env.pop(key, None)

        # Run Claude CLI with clean environment
        # Pass prompt via stdin instead of -p to avoid shell parsing issues
        result = subprocess.run(
            ['claude', '--model', cli_model, '--output-format', 'text'],
            cwd=PROJECT_DIR,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            env=clean_env  # Use clean environment with only OAuth token
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            # Check for API credit errors - this means OAuth isn't being used properly
            if 'credit balance' in error_msg.lower() or 'api key' in error_msg.lower():
                raise Exception(
                    "CLI is still using API mode instead of OAuth. "
                    "Check Claude CLI configuration. "
                    "Try running 'claude /logout' then 'claude /login' on the server."
                )
            raise Exception(f"CLI failed: {error_msg}")

        return parse_suggestions_response(result.stdout, direction, max_suggestions)

    except subprocess.TimeoutExpired:
        raise Exception("Claude CLI timed out after 5 minutes")
    except FileNotFoundError:
        raise Exception("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code")
    except Exception as e:
        raise Exception(f"CLI OAuth error: {str(e)}")


def save_suggestions_to_db(suggestions):
    """Save generated suggestions to the database."""
    suggestion_ids = []
    for sug in suggestions:
        suggestion_id = database.add_incept_suggestion(
            title=sug['title'],
            description=sug['description'],
            implementation_details=sug['implementation_details'],
            category=sug.get('category', 'feature'),
            priority=sug.get('priority', 3),
            context=sug.get('context'),
            estimated_effort=sug.get('estimated_effort'),
            dependencies=sug.get('dependencies')
        )
        suggestion_ids.append(suggestion_id)
    return suggestion_ids


def generate_and_save_suggestions(direction, context=None, max_suggestions=10):
    """Generate suggestions and save them to the database."""
    suggestions = generate_suggestions(direction, context, max_suggestions)
    suggestion_ids = save_suggestions_to_db(suggestions)

    # Pair IDs with suggestions
    for i, suggestion_id in enumerate(suggestion_ids):
        if i < len(suggestions):
            suggestions[i]['id'] = suggestion_id

    return suggestions
