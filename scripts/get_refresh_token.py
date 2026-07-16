#!/usr/bin/env python3
"""One-shot Google OAuth flow for Dayrunly. Scope: Calendar ONLY.

Runs the OAuth "Desktop app" flow in your browser via a localhost redirect,
prints the refresh token, and can store everything in AWS SSM Parameter Store.

Usage:
    python3 scripts/get_refresh_token.py [path/to/client_secret.json] [--push-ssm]

    client_secret.json  downloaded from Google Cloud console (default: ./client_secret.json)
    --push-ssm          store client_id / client_secret / refresh_token as
                        SecureStrings under /dayrunly/google/* (requires AWS
                        credentials in the environment; params tagged product=dayrunly)

Standard library only. No secrets are written to disk by this script.
"""

import http.server
import json
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/calendar"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SSM_PREFIX = "/dayrunly/google/"


def load_client_secret(path):
    with open(path) as f:
        data = json.load(f)
    key = "installed" if "installed" in data else "web"
    return data[key]["client_id"], data[key]["client_secret"]


def wait_for_code(expected_state):
    """Serve one localhost request and capture the ?code= from Google's redirect."""
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if params.get("state", [""])[0] != expected_state:
                self.wfile.write(b"State mismatch - close this tab and retry.")
                return
            if "code" in params:
                result["code"] = params["code"][0]
                self.wfile.write(b"<h2>Dayrunly authorized. You can close this tab.</h2>")
            else:
                self.wfile.write(b"Authorization failed: " + repr(params).encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    return server, port, result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    push_ssm = "--push-ssm" in sys.argv
    secret_path = args[0] if args else "client_secret.json"

    client_id, client_secret = load_client_secret(secret_path)
    state = secrets.token_urlsafe(16)
    server, port, result = wait_for_code(state)
    redirect_uri = f"http://127.0.0.1:{port}"

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # ask for a refresh token
        "prompt": "consent",        # force one to be issued even on re-auth
        "state": state,
    })
    print("Opening browser for Google authorization...")
    print("If it doesn't open, visit:\n\n" + url + "\n")
    webbrowser.open(url)

    while "code" not in result:
        server.handle_request()
    server.server_close()

    body = urllib.parse.urlencode({
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as resp:
        tokens = json.load(resp)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(f"No refresh_token in response: {tokens}")

    granted = tokens.get("scope", "")
    if granted and granted != SCOPE:
        sys.exit(f"Unexpected scopes granted ({granted}) - expected only {SCOPE}. Aborting.")

    print("\nRefresh token obtained (calendar scope only).")

    if push_ssm:
        for name, value in [("client_id", client_id),
                            ("client_secret", client_secret),
                            ("refresh_token", refresh_token)]:
            param = SSM_PREFIX + name
            create = ["aws", "ssm", "put-parameter", "--name", param,
                      "--type", "SecureString", "--value", value,
                      "--tags", "Key=product,Value=dayrunly"]
            # --tags and --overwrite are mutually exclusive; fall back to overwrite
            if subprocess.run(create, capture_output=True).returncode != 0:
                subprocess.run(["aws", "ssm", "put-parameter", "--name", param,
                                "--type", "SecureString", "--value", value,
                                "--overwrite"], check=True, capture_output=True)
            print(f"  stored {param}")
        print("Done. Secrets live in SSM only.")
    else:
        print("\nRe-run with --push-ssm to store credentials in SSM Parameter Store.")
        print("(Refresh token not printed to avoid it landing in shell history/logs.)")


if __name__ == "__main__":
    main()
