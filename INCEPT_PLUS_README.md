# Incept+ - AI-Powered Continuous Improvement System

Incept+ is an advanced feature that extends the Incept system with intelligent, AI-powered improvement suggestions and automated implementation.

## Overview

Incept+ uses Claude AI to:
1. Generate contextual improvement suggestions based on your direction
2. Provide detailed implementation plans for each suggestion
3. Automatically implement accepted suggestions via the Incept system
4. Track all implemented improvements with commit hashes
5. Allow toggling improvements on/off or rolling them back
6. Run in "auto-mode" for continuous, autonomous improvements

## Features

### 1. Smart Suggestion Generation

Navigate to `/incept-plus` and use the "Generate Suggestions" tab to:
- Describe what you want to improve (e.g., "Make the UI more responsive", "Add real-time features")
- Provide additional context about your codebase
- Set how many suggestions you want (1-20)
- Get AI-generated suggestions with:
  - Clear titles and descriptions
  - Detailed implementation steps
  - Category tags (feature, bugfix, performance, etc.)
  - Priority levels (1-5)
  - Estimated effort (small, medium, large)
  - Dependencies

### 2. Suggestion Management

In the "Suggestions" tab you can:
- **View Details**: See full implementation instructions
- **Accept**: Mark as approved for implementation
- **Reject**: Remove from the list
- **Implement Now**: Create an Incept request immediately

### 3. Implementation Tracking

All implemented improvements are tracked in the "Improvements" tab:
- View all implementations with metadata
- See commit hashes for each change
- Toggle improvements on/off
- Rollback improvements by reverting commits

### 4. Auto-Mode (Dangerous!)

The "Auto-Mode" tab enables fully autonomous operation:
- Set a direction (e.g., "improve performance")
- Set max number of suggestions
- System will:
  - Generate suggestions
  - Auto-accept all of them
  - Create Incept requests
  - Implement changes automatically
  - Continue until max suggestions reached

**Warning**: Auto-mode makes real changes to your codebase without manual review!

## Architecture

### Database Tables

1. **incept_suggestions**: Stores generated suggestions
   - title, description, implementation_details
   - category, priority, estimated_effort
   - status (suggested, accepted, rejected, implementing, implemented)

2. **incept_improvements**: Tracks implemented changes
   - Links to suggestion_id
   - commit_hash, files_changed
   - enabled flag (for toggles)
   - rollback_info (JSON with git metadata)

3. **incept_auto_sessions**: Manages auto-mode runs
   - direction, max_suggestions
   - suggestions_generated, suggestions_implemented
   - status (running, stopped, completed, error)

4. **incept_plus_settings**: System configuration
   - auto_mode_enabled, auto_mode_interval
   - suggestion_model, max_list_length
   - auto_implement_approved

### Backend Modules

1. **incept_plus_suggester.py**: Suggestion generation
   - `generate_suggestions()`: Calls Claude API
   - `save_suggestions_to_db()`: Persists to database
   - `generate_and_save_suggestions()`: Combined flow

2. **incept_plus_tracker.py**: Implementation tracking
   - `track_improvement_implementation()`: Records after Incept completes
   - `rollback_improvement()`: Git revert functionality
   - `check_improvement_status()`: Query improvement state

3. **incept_plus_auto.py**: Auto-mode worker
   - `process_auto_mode_session()`: Process one iteration
   - `run_auto_mode_worker()`: Main loop (runs as background process)

### API Endpoints

All endpoints require login (`@login_required`):

**Suggestion Generation:**
- `POST /api/incept-plus/suggest` - Generate new suggestions
- `GET /api/incept-plus/suggestions` - List suggestions (with filters)
- `GET /api/incept-plus/suggestion/<id>` - Get single suggestion

**Suggestion Actions:**
- `POST /api/incept-plus/suggestion/<id>/accept` - Accept suggestion
- `POST /api/incept-plus/suggestion/<id>/reject` - Reject suggestion
- `POST /api/incept-plus/suggestion/<id>/implement` - Create Incept request

**Improvement Management:**
- `GET /api/incept-plus/improvements` - List improvements
- `POST /api/incept-plus/improvement/<id>/toggle` - Enable/disable
- `POST /api/incept-plus/improvement/<id>/rollback` - Revert changes

**Auto-Mode:**
- `POST /api/incept-plus/auto-mode/start` - Start auto-mode
- `POST /api/incept-plus/auto-mode/stop` - Stop auto-mode
- `GET /api/incept-plus/auto-mode/status` - Check status

**Settings:**
- `GET /api/incept-plus/settings` - Get settings
- `POST /api/incept-plus/settings` - Update settings

**Tracking:**
- `POST /api/incept-plus/track-implementation` - Record implementation

### Frontend

**Template**: `templates/incept_plus_v6.html`

Features:
- 4 tabs: Generate, Suggestions, Improvements, Auto-Mode
- Real-time stats dashboard
- Color-coded badges for categories and priorities
- Expandable implementation details
- Toggle switches for enable/disable
- Rollback buttons with confirmation

**Styling**: Integrated with v6 theme system
- Dark/light mode support
- Consistent with other dashboard pages
- Responsive design

## Usage Examples

### Example 1: Generate UI Improvements

1. Go to `/incept-plus`
2. In "Generate Suggestions" tab:
   ```
   Direction: Make the dashboard more responsive and mobile-friendly
   Context: Focus on the messages list and navigation
   Suggestions: 5
   ```
3. Click "Generate Suggestions"
4. Review suggestions in "Suggestions" tab
5. Accept the ones you like
6. Click "Implement Now" for each

### Example 2: Auto-Mode for Performance

1. Go to "Auto-Mode" tab
2. Enter:
   ```
   Direction: Optimize database queries and reduce page load times
   Max Suggestions: 10
   ```
3. Click "Start Auto-Mode"
4. System will generate and implement 10 performance improvements
5. Monitor in "Improvements" tab
6. Toggle off or rollback any problematic changes

### Example 3: Rollback an Improvement

1. Go to "Improvements" tab
2. Find the improvement you want to revert
3. Click "Rollback"
4. Confirm the action
5. System creates a git revert commit
6. Improvement is disabled

## Configuration

Settings are stored in the database and can be modified via API or in the UI:

```python
# Default settings
{
    'auto_mode_enabled': 0,           # Auto-mode disabled by default
    'auto_mode_interval': 300,        # 5 minutes between iterations
    'suggestion_model': 'claude-sonnet-4-20250514',  # Model for suggestions
    'max_list_length': 10,            # Default suggestion count
    'auto_implement_approved': 1      # Auto-implement accepted suggestions
}
```

## Security Considerations

1. **Authentication**: All endpoints require login
2. **Confirmation**: Destructive actions require confirmation
3. **Git tracking**: All changes are committed for auditability
4. **Rollback capability**: Changes can be reverted
5. **Manual review**: Non-auto-mode requires manual acceptance

## Running Auto-Mode Worker

To run the auto-mode worker as a background process:

```bash
cd /opt/render/project/src
python incept_plus_auto.py &
```

Or add to systemd/supervisor for production use.

## Integration with Incept

Incept+ is fully integrated with the existing Incept system:
- Suggestions become Incept requests when implemented
- Uses same API mode, model, and git settings
- Shares authentication and user session
- Appears in regular Incept request logs

## Limitations

1. Suggestion quality depends on Claude's understanding of your codebase
2. Auto-mode can generate many commits rapidly
3. Rollback uses git revert, which creates new commits (not hard reset)
4. No automatic conflict resolution if rollback fails
5. Feature flags are tracked but not automatically applied to code

## Future Enhancements

Potential improvements:
- Smart conflict resolution for rollbacks
- Automatic feature flag code generation
- A/B testing for improvements
- ML-based suggestion ranking
- Integration with CI/CD pipelines
- Slack/email notifications for auto-mode activity
- Suggestion templates and presets
- Batch implementation with dependency ordering

## Troubleshooting

**Problem**: Suggestions are generic or not relevant
- **Solution**: Provide more specific direction and context

**Problem**: Auto-mode is not running
- **Solution**: Check if worker process is running, check database for active session

**Problem**: Rollback failed
- **Solution**: Check git status, may need manual intervention

**Problem**: Implementation gets stuck
- **Solution**: Check Incept processor status, check Claude API key

## Support

For issues or questions:
- Check system logs in `/logs` directory
- Review Incept request logs for implementation details
- Check git history for commit information
- Monitor auto-mode session status in database
