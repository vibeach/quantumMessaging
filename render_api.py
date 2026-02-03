#!/usr/bin/env python3
"""
Render API Helper
Manage Render service: env vars, deploys, restarts
"""

import requests
import sys
import json
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

API_BASE = "https://api.render.com/v1"
HEADERS = {
    "Authorization": f"Bearer {config.RENDER_API_KEY}",
    "Content-Type": "application/json"
}
SERVICE_ID = config.RENDER_SERVICE_ID


def _request(method, endpoint, data=None):
    """Make API request."""
    url = f"{API_BASE}{endpoint}"
    resp = requests.request(method, url, headers=HEADERS, json=data)
    if resp.status_code >= 400:
        print(f"Error {resp.status_code}: {resp.text}")
        return None
    return resp.json() if resp.text else {}


# ==================== ENV VARS ====================

def list_env_vars():
    """List all environment variables."""
    result = _request("GET", f"/services/{SERVICE_ID}/env-vars")
    if result:
        for item in result:
            ev = item.get('envVar', item)
            value = ev.get('value', '***')
            if len(value) > 50:
                value = value[:50] + "..."
            print(f"  {ev['key']} = {value}")
    return result


def get_env_var(key):
    """Get a specific env var."""
    result = _request("GET", f"/services/{SERVICE_ID}/env-vars")
    if result:
        for item in result:
            ev = item.get('envVar', item)
            if ev['key'] == key:
                return ev['value']
    return None


def set_env_var(key, value):
    """Set/update an environment variable."""
    # First check if it exists
    result = _request("GET", f"/services/{SERVICE_ID}/env-vars")
    exists = False
    if result:
        for item in result:
            ev = item.get('envVar', item)
            if ev['key'] == key:
                exists = True
                break

    if exists:
        # Update existing
        result = _request("PUT", f"/services/{SERVICE_ID}/env-vars/{key}", {"value": value})
    else:
        # Create new
        result = _request("POST", f"/services/{SERVICE_ID}/env-vars", {"key": key, "value": value})

    if result:
        print(f"  ✓ Set {key}")
    return result


def delete_env_var(key):
    """Delete an environment variable."""
    result = _request("DELETE", f"/services/{SERVICE_ID}/env-vars/{key}")
    if result is not None:
        print(f"  ✓ Deleted {key}")
    return result


# ==================== DEPLOYS ====================

def trigger_deploy(clear_cache=False):
    """Trigger a new deploy."""
    data = {"clearCache": "clear" if clear_cache else "do_not_clear"}
    result = _request("POST", f"/services/{SERVICE_ID}/deploys", data)
    if result:
        deploy = result.get('deploy', result)
        print(f"  ✓ Deploy triggered: {deploy.get('id')}")
        print(f"    Status: {deploy.get('status')}")
    return result


def list_deploys(limit=5):
    """List recent deploys."""
    result = _request("GET", f"/services/{SERVICE_ID}/deploys?limit={limit}")
    if result:
        for item in result:
            d = item.get('deploy', item)
            status = d.get('status', 'unknown')
            created = d.get('createdAt', '')[:19]
            commit = d.get('commit', {}).get('message', '')[:40] if d.get('commit') else ''
            status_icon = {'live': '✓', 'build_failed': '✗', 'building': '⏳', 'created': '○'}.get(status, '?')
            print(f"  {status_icon} {status:12} {created}  {commit}")
    return result


def get_deploy_status():
    """Get current deploy status."""
    result = _request("GET", f"/services/{SERVICE_ID}/deploys?limit=1")
    if result and len(result) > 0:
        d = result[0].get('deploy', result[0])
        return d.get('status')
    return None


# ==================== SERVICE ====================

def get_service_info():
    """Get service information."""
    result = _request("GET", f"/services/{SERVICE_ID}")
    if result:
        s = result
        print(f"  Name: {s.get('name')}")
        print(f"  URL: {s.get('serviceDetails', {}).get('url')}")
        print(f"  Status: {s.get('suspended')}")
        print(f"  Branch: {s.get('branch')}")
        print(f"  Auto Deploy: {s.get('autoDeploy')}")
    return result


def restart_service():
    """Restart the service."""
    result = _request("POST", f"/services/{SERVICE_ID}/restart")
    if result is not None:
        print("  ✓ Restart triggered")
    return result


def suspend_service():
    """Suspend the service."""
    result = _request("POST", f"/services/{SERVICE_ID}/suspend")
    if result is not None:
        print("  ✓ Service suspended")
    return result


def resume_service():
    """Resume the service."""
    result = _request("POST", f"/services/{SERVICE_ID}/resume")
    if result is not None:
        print("  ✓ Service resumed")
    return result


# ==================== CLI ====================

def main():
    if len(sys.argv) < 2:
        print("Render API Helper")
        print("=" * 40)
        print("Usage: python render_api.py <command> [args]")
        print("")
        print("Commands:")
        print("  env                  List env vars")
        print("  env get <key>        Get env var")
        print("  env set <key> <val>  Set env var")
        print("  env del <key>        Delete env var")
        print("")
        print("  deploy               Trigger deploy")
        print("  deploy --clear       Deploy with cache clear")
        print("  deploys              List recent deploys")
        print("  status               Get deploy status")
        print("")
        print("  info                 Service info")
        print("  restart              Restart service")
        print("  suspend              Suspend service")
        print("  resume               Resume service")
        return

    cmd = sys.argv[1]

    if cmd == "env":
        if len(sys.argv) == 2:
            print("Environment Variables:")
            list_env_vars()
        elif sys.argv[2] == "get" and len(sys.argv) > 3:
            val = get_env_var(sys.argv[3])
            print(f"{sys.argv[3]} = {val}")
        elif sys.argv[2] == "set" and len(sys.argv) > 4:
            set_env_var(sys.argv[3], sys.argv[4])
        elif sys.argv[2] == "del" and len(sys.argv) > 3:
            delete_env_var(sys.argv[3])
        else:
            print("Usage: env [get|set|del] <key> [value]")

    elif cmd == "deploy":
        clear = "--clear" in sys.argv
        print("Triggering deploy...")
        trigger_deploy(clear_cache=clear)

    elif cmd == "deploys":
        print("Recent Deploys:")
        list_deploys()

    elif cmd == "status":
        status = get_deploy_status()
        print(f"Deploy Status: {status}")

    elif cmd == "info":
        print("Service Info:")
        get_service_info()

    elif cmd == "restart":
        print("Restarting...")
        restart_service()

    elif cmd == "suspend":
        suspend_service()

    elif cmd == "resume":
        resume_service()

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
