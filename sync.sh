#!/bin/bash
# sync.sh - Auto-sync local and remote changes
# Usage: ./sync.sh [push|pull|status]

set -e
cd "$(dirname "$0")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Git Sync ===${NC}"

# Get current state
BRANCH=$(git branch --show-current)
LOCAL_CHANGES=$(git status --porcelain)
git fetch origin --quiet

LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse origin/$BRANCH 2>/dev/null || echo "none")
MERGE_BASE=$(git merge-base HEAD origin/$BRANCH 2>/dev/null || echo "none")

# Determine sync state
if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    SYNC_STATE="synced"
elif [ "$LOCAL_HEAD" = "$MERGE_BASE" ]; then
    SYNC_STATE="behind"
elif [ "$REMOTE_HEAD" = "$MERGE_BASE" ]; then
    SYNC_STATE="ahead"
else
    SYNC_STATE="diverged"
fi

# Status command
status() {
    echo -e "Branch: ${GREEN}$BRANCH${NC}"

    case $SYNC_STATE in
        synced)
            echo -e "Remote: ${GREEN}✓ In sync${NC}"
            ;;
        behind)
            BEHIND_COUNT=$(git rev-list --count HEAD..origin/$BRANCH)
            echo -e "Remote: ${YELLOW}↓ $BEHIND_COUNT commit(s) behind${NC}"
            ;;
        ahead)
            AHEAD_COUNT=$(git rev-list --count origin/$BRANCH..HEAD)
            echo -e "Remote: ${BLUE}↑ $AHEAD_COUNT commit(s) ahead${NC}"
            ;;
        diverged)
            echo -e "Remote: ${RED}⚠ Diverged (need merge)${NC}"
            ;;
    esac

    if [ -n "$LOCAL_CHANGES" ]; then
        CHANGED_COUNT=$(echo "$LOCAL_CHANGES" | wc -l | tr -d ' ')
        echo -e "Local:  ${YELLOW}$CHANGED_COUNT file(s) modified${NC}"
    else
        echo -e "Local:  ${GREEN}✓ Clean${NC}"
    fi
}

# Pull command - get remote changes
pull() {
    echo -e "${BLUE}Pulling remote changes...${NC}"

    # Stash local changes if any
    if [ -n "$LOCAL_CHANGES" ]; then
        echo -e "${YELLOW}Stashing local changes...${NC}"
        git stash push -m "auto-stash before sync"
        STASHED=1
    fi

    # Pull with rebase for cleaner history
    if git pull --rebase origin $BRANCH; then
        echo -e "${GREEN}✓ Pulled successfully${NC}"
    else
        echo -e "${RED}✗ Pull failed - resolve conflicts manually${NC}"
        if [ "$STASHED" = "1" ]; then
            echo -e "${YELLOW}Your changes are stashed. Run 'git stash pop' after resolving.${NC}"
        fi
        exit 1
    fi

    # Restore stashed changes
    if [ "$STASHED" = "1" ]; then
        echo -e "${YELLOW}Restoring local changes...${NC}"
        if git stash pop; then
            echo -e "${GREEN}✓ Local changes restored${NC}"
        else
            echo -e "${RED}✗ Conflict restoring changes. Resolve with 'git stash show -p | git apply'${NC}"
        fi
    fi
}

# Push command - send local changes
push() {
    if [ -z "$LOCAL_CHANGES" ] && [ "$SYNC_STATE" = "synced" ]; then
        echo -e "${GREEN}Nothing to push - already in sync${NC}"
        return
    fi

    # Pull first if behind
    if [ "$SYNC_STATE" = "behind" ] || [ "$SYNC_STATE" = "diverged" ]; then
        echo -e "${YELLOW}Pulling remote changes first...${NC}"
        pull
    fi

    # Commit local changes if any
    if [ -n "$LOCAL_CHANGES" ]; then
        echo -e "${BLUE}Committing local changes...${NC}"
        git add -A

        # Generate commit message from changed files
        CHANGED_FILES=$(git diff --cached --name-only | head -3 | tr '\n' ', ' | sed 's/,$//')
        MSG="Local changes: $CHANGED_FILES"

        git commit -m "$MSG"
        echo -e "${GREEN}✓ Committed: $MSG${NC}"
    fi

    # Push
    echo -e "${BLUE}Pushing to remote...${NC}"
    if git push origin $BRANCH; then
        echo -e "${GREEN}✓ Pushed successfully${NC}"
    else
        echo -e "${RED}✗ Push failed${NC}"
        exit 1
    fi
}

# Auto command - smart sync
auto() {
    status
    echo ""

    case $SYNC_STATE in
        synced)
            if [ -n "$LOCAL_CHANGES" ]; then
                echo -e "${BLUE}Local changes detected. Pushing...${NC}"
                push
            else
                echo -e "${GREEN}Already in sync, nothing to do${NC}"
            fi
            ;;
        behind)
            echo -e "${BLUE}Behind remote. Pulling...${NC}"
            pull
            if [ -n "$(git status --porcelain)" ]; then
                echo -e "${BLUE}Local changes after pull. Pushing...${NC}"
                push
            fi
            ;;
        ahead)
            echo -e "${BLUE}Ahead of remote. Pushing...${NC}"
            push
            ;;
        diverged)
            echo -e "${YELLOW}Diverged from remote. Pulling then pushing...${NC}"
            pull
            push
            ;;
    esac

    echo ""
    echo -e "${GREEN}=== Sync Complete ===${NC}"
}

# Main
case "${1:-auto}" in
    status|s)
        status
        ;;
    pull|down|d)
        pull
        ;;
    push|up|u)
        push
        ;;
    auto|sync|"")
        auto
        ;;
    *)
        echo "Usage: $0 [status|pull|push|auto]"
        echo "  status - Show sync state"
        echo "  pull   - Pull remote changes"
        echo "  push   - Commit & push local changes"
        echo "  auto   - Smart sync (default)"
        exit 1
        ;;
esac
