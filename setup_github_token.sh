#!/bin/bash
# Setup GitHub token for Render git push
# Run this script locally, then add the token to Render

echo "=========================================="
echo "  GitHub Token Setup for Render"
echo "=========================================="
echo ""

# Check if gh CLI is installed
if command -v gh &> /dev/null; then
    echo "GitHub CLI detected. Checking auth status..."

    if gh auth status &> /dev/null; then
        echo "You're logged into GitHub CLI."
        echo ""
        echo "Creating a new token with repo scope..."

        # Create token using gh CLI
        TOKEN=$(gh auth token 2>/dev/null)

        if [ -n "$TOKEN" ]; then
            echo ""
            echo "=========================================="
            echo "  Your GitHub Token:"
            echo "=========================================="
            echo ""
            echo "$TOKEN"
            echo ""
            echo "=========================================="
            echo ""
            echo "Add these environment variables to Render:"
            echo ""
            echo "  GITHUB_REPO_URL = https://github.com/vibeach/telegram-monitor.git"
            echo "  GITHUB_TOKEN    = $TOKEN"
            echo ""

            # Copy to clipboard if possible
            if command -v pbcopy &> /dev/null; then
                echo "$TOKEN" | pbcopy
                echo "(Token copied to clipboard)"
            fi
        else
            echo "Could not get token. Creating a new one..."
            echo ""
            echo "Run: gh auth refresh -s repo"
            echo "Then run this script again."
        fi
    else
        echo "Not logged in. Running: gh auth login"
        gh auth login -s repo
        echo ""
        echo "Now run this script again to get your token."
    fi
else
    echo "GitHub CLI (gh) not installed."
    echo ""
    echo "Option 1: Install gh CLI (recommended)"
    echo "  brew install gh"
    echo "  Then run this script again."
    echo ""
    echo "Option 2: Create token manually"
    echo "  Opening GitHub token page in browser..."
    echo ""

    # Open GitHub token creation page
    TOKEN_URL="https://github.com/settings/tokens/new?description=Render%20Telegram%20Dashboard&scopes=repo"

    if command -v open &> /dev/null; then
        open "$TOKEN_URL"
    elif command -v xdg-open &> /dev/null; then
        xdg-open "$TOKEN_URL"
    else
        echo "Open this URL in your browser:"
        echo "$TOKEN_URL"
    fi

    echo ""
    echo "Steps:"
    echo "  1. Set expiration (90 days or custom)"
    echo "  2. Check 'repo' scope (should be pre-selected)"
    echo "  3. Click 'Generate token'"
    echo "  4. Copy the token"
    echo ""
    echo "Then add to Render environment variables:"
    echo "  GITHUB_REPO_URL = https://github.com/vibeach/telegram-monitor.git"
    echo "  GITHUB_TOKEN    = <your-token>"
fi

echo ""
echo "=========================================="
