import json
import hmac
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PROBLEMS_FILE = Path(os.environ.get("PROBLEMS_FILE", DATA_DIR / "problems.json"))
MAX_REQUEST_BYTES = 100_000
SESSION_COOKIE_NAME = "duhdecoder_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-session-secret-change-me")
GOOGLE_REQUEST = google_requests.Request()

RUNNER_TEMPLATE = textwrap.dedent(
    """
    import importlib.util
    import json
    import traceback

    spec = importlib.util.spec_from_file_location("submission", "submission.py")
    module = importlib.util.module_from_spec(spec)

    try:
        spec.loader.exec_module(module)
    except Exception:
        print(json.dumps({{
            "status": "runtime_error",
            "message": traceback.format_exc(),
            "results": []
        }}))
        raise SystemExit(0)

    function_name = {function_name!r}
    tests = {tests_json}

    if not hasattr(module, function_name):
        print(json.dumps({{
            "status": "runtime_error",
            "message": f"Function '{{function_name}}' was not found in your code.",
            "results": []
        }}))
        raise SystemExit(0)

    target = getattr(module, function_name)
    results = []
    overall_status = "accepted"
    message = "All test cases passed."

    for index, test in enumerate(tests, start=1):
        try:
            actual = target(*test["input"])
            passed = actual == test["output"]
            results.append({{
                "test_number": index,
                "input": test["input"],
                "expected": test["output"],
                "actual": actual,
                "passed": passed
            }})
            if not passed:
                overall_status = "wrong_answer"
                message = "One or more test cases failed."
                break
        except Exception:
            overall_status = "runtime_error"
            message = traceback.format_exc()
            results.append({{
                "test_number": index,
                "input": test["input"],
                "expected": test["output"],
                "actual": None,
                "passed": False
            }})
            break

    print(json.dumps({{
        "status": overall_status,
        "message": message,
        "results": results
    }}))
    """
)

DEFAULT_PROBLEMS = [
    {
        "id": "sum-two-numbers",
        "title": "Sum Two Numbers",
        "difficulty": "Easy",
        "description": (
            "The starter code is buggy. Fix `solve(a, b)` so it returns the sum of "
            "two integers."
        ),
        "starter_code": textwrap.dedent(
            """
            def solve(a, b):
                # Bug: this subtracts instead of adding
                return a - b
            """
        ).strip(),
        "function_name": "solve",
        "mode": "Bug Fix",
        "samples": [
            {"input": [2, 3], "output": 5},
            {"input": [-4, 9], "output": 5},
        ],
        "tests": [
            {"input": [2, 3], "output": 5},
            {"input": [-4, 9], "output": 5},
            {"input": [0, 0], "output": 0},
            {"input": [12345, 67890], "output": 80235},
        ],
    },
    {
        "id": "is-palindrome",
        "title": "Palindrome Check",
        "difficulty": "Easy",
        "description": (
            "The starter code is buggy. Fix `solve(text)` so it returns `True` when "
            "the input is a palindrome and `False` otherwise."
        ),
        "starter_code": textwrap.dedent(
            """
            def solve(text):
                # Bug: this returns the opposite answer
                return text != text[::-1]
            """
        ).strip(),
        "function_name": "solve",
        "mode": "Bug Fix",
        "samples": [
            {"input": ["level"], "output": True},
            {"input": ["hello"], "output": False},
        ],
        "tests": [
            {"input": ["level"], "output": True},
            {"input": ["hello"], "output": False},
            {"input": ["racecar"], "output": True},
            {"input": [""], "output": True},
        ],
    },
]

PROBLEMS = []
PROBLEM_INDEX = {}


def serialize_problem(problem):
    data = deepcopy(problem)
    data.pop("tests", None)
    return data


def rebuild_problem_index():
    global PROBLEM_INDEX
    PROBLEM_INDEX = {problem["id"]: problem for problem in PROBLEMS}


def save_problems():
    PROBLEMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROBLEMS_FILE.write_text(json.dumps(PROBLEMS, indent=2), encoding="utf-8")


def load_problems():
    global PROBLEMS
    if PROBLEMS_FILE.exists():
        try:
            PROBLEMS = json.loads(PROBLEMS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Could not parse problems file at {PROBLEMS_FILE}: {error}"
            ) from error
    else:
        PROBLEMS = deepcopy(DEFAULT_PROBLEMS)
        save_problems()

    rebuild_problem_index()


def run_submission(problem, code):
    runner_code = RUNNER_TEMPLATE.format(
        function_name=problem["function_name"],
        tests_json=repr(problem["tests"]),
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        submission_path = Path(temp_dir) / "submission.py"
        runner_path = Path(temp_dir) / "runner.py"
        submission_path.write_text(code, encoding="utf-8")
        runner_path.write_text(runner_code, encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, str(runner_path)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "message": "Execution timed out after 3 seconds.",
                "results": [],
            }

    output = completed.stdout.strip()
    if not output:
        stderr = completed.stderr.strip() or "No output was produced."
        return {
            "status": "runtime_error",
            "message": stderr,
            "results": [],
        }

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {
            "status": "runtime_error",
            "message": output,
            "results": [],
        }


def b64encode_text(value):
    return urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def b64decode_text(value):
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(f"{value}{padding}").decode("utf-8")


def sign_value(value):
    digest = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        value.encode("utf-8"),
        "sha256",
    ).hexdigest()
    return digest


def build_session_cookie(user_info):
    payload = {
        "sub": user_info["sub"],
        "email": user_info.get("email", ""),
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    encoded = b64encode_text(json.dumps(payload, separators=(",", ":")))
    signature = sign_value(encoded)
    return f"{encoded}.{signature}"


def parse_session_cookie(raw_cookie):
    if not raw_cookie or "." not in raw_cookie:
        return None

    encoded, signature = raw_cookie.rsplit(".", 1)
    expected_signature = sign_value(encoded)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(b64decode_text(encoded))
    except (ValueError, json.JSONDecodeError):
        return None

    if payload.get("exp", 0) < int(time.time()):
        return None

    return payload


def is_authenticated(handler):
    cookie_header = handler.headers.get("Cookie", "")
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get(SESSION_COOKIE_NAME)
    if not morsel:
        return None
    return parse_session_cookie(morsel.value)


def set_session_cookie(handler, user_info):
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = build_session_cookie(user_info)
    cookie[SESSION_COOKIE_NAME]["path"] = "/"
    cookie[SESSION_COOKIE_NAME]["httponly"] = True
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    if os.environ.get("PORT"):
        cookie[SESSION_COOKIE_NAME]["secure"] = True
    return cookie.output(header="").strip()


def clear_session_cookie(handler):
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = ""
    cookie[SESSION_COOKIE_NAME]["path"] = "/"
    cookie[SESSION_COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    cookie[SESSION_COOKIE_NAME]["max-age"] = 0
    cookie[SESSION_COOKIE_NAME]["httponly"] = True
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    if os.environ.get("PORT"):
        cookie[SESSION_COOKIE_NAME]["secure"] = True
    return cookie.output(header="").strip()


def verify_google_credential(credential):
    if not GOOGLE_CLIENT_ID:
        raise ValueError("Server is missing GOOGLE_CLIENT_ID configuration.")

    token_info = id_token.verify_oauth2_token(
        credential,
        GOOGLE_REQUEST,
        GOOGLE_CLIENT_ID,
    )

    if token_info["iss"] not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Invalid token issuer.")

    return {
        "sub": token_info["sub"],
        "email": token_info.get("email", ""),
        "name": token_info.get("name", ""),
        "picture": token_info.get("picture", ""),
    }


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _send_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_redirect(self, location, cookie_header=None):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        if cookie_header:
            self.send_header("Set-Cookie", cookie_header)
        self.end_headers()

    def do_GET(self):
        session = is_authenticated(self)
        parsed = urlparse(self.path)

        if self.path == "/healthz":
            return self._send_json({"ok": True, "problem_count": len(PROBLEMS)})
        if self.path == "/api/auth/session":
            if not session:
                return self._send_json(
                    {"authenticated": False}, status=HTTPStatus.UNAUTHORIZED
                )
            return self._send_json({"authenticated": True, "user": session})
        if self.path == "/login":
            if session:
                return self._send_redirect("/")
            return self._send_file(
                STATIC_DIR / "login.html",
                replacements={"__GOOGLE_CLIENT_ID__": GOOGLE_CLIENT_ID},
            )
        if self.path == "/api/problems":
            if not session:
                return self._send_json(
                    {"error": "Authentication required."},
                    status=HTTPStatus.UNAUTHORIZED,
                )
            return self._send_json([serialize_problem(problem) for problem in PROBLEMS])
        if self.path.startswith("/api/problems/"):
            if not session:
                return self._send_json(
                    {"error": "Authentication required."},
                    status=HTTPStatus.UNAUTHORIZED,
                )
            problem_id = self.path.rsplit("/", 1)[-1]
            problem = PROBLEM_INDEX.get(problem_id)
            if not problem:
                return self._send_json(
                    {"error": "Problem not found."}, status=HTTPStatus.NOT_FOUND
                )
            return self._send_json(serialize_problem(problem))
        if self.path == "/":
            if not session:
                return self._send_redirect("/login")
            return self._send_file(STATIC_DIR / "index.html")
        if self.path == "/index.html":
            if not session:
                return self._send_redirect("/login")
            return self._send_file(STATIC_DIR / "index.html")
        if parsed.path in {"/styles.css", "/app.js", "/login.js"}:
            return super().do_GET()
        return super().do_GET()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_REQUEST_BYTES:
                return self._send_json(
                    {"error": "Request payload is too large."},
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return self._send_json(
                {"error": "Invalid JSON payload."}, status=HTTPStatus.BAD_REQUEST
            )

        session = is_authenticated(self)

        if self.path == "/api/auth/google":
            credential = payload.get("credential", "")
            if not credential:
                return self._send_json(
                    {"error": "Missing Google credential."},
                    status=HTTPStatus.BAD_REQUEST,
                )
            try:
                user_info = verify_google_credential(credential)
            except ValueError as error:
                return self._send_json(
                    {"error": str(error)}, status=HTTPStatus.UNAUTHORIZED
                )

            response_payload = json.dumps(
                {"authenticated": True, "user": user_info}
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_payload)))
            self.send_header("Set-Cookie", set_session_cookie(self, user_info))
            self.end_headers()
            self.wfile.write(response_payload)
            return

        if self.path == "/api/auth/logout":
            response_payload = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_payload)))
            self.send_header("Set-Cookie", clear_session_cookie(self))
            self.end_headers()
            self.wfile.write(response_payload)
            return

        if self.path == "/api/run":
            if not session:
                return self._send_json(
                    {"error": "Authentication required."},
                    status=HTTPStatus.UNAUTHORIZED,
                )
            problem_id = payload.get("problem_id")
            code = payload.get("code", "")
            if not problem_id or not code.strip():
                return self._send_json(
                    {"error": "Both problem_id and code are required."},
                    status=HTTPStatus.BAD_REQUEST,
                )

            problem = PROBLEM_INDEX.get(problem_id)
            if not problem:
                return self._send_json(
                    {"error": "Problem not found."}, status=HTTPStatus.NOT_FOUND
                )

            result = run_submission(problem, code)
            return self._send_json(result)

        return self._send_json(
            {"error": "Route not found."}, status=HTTPStatus.NOT_FOUND
        )

    def _send_file(self, path, replacements=None):
        if path.suffix == ".html":
            text = path.read_text(encoding="utf-8")
            for old, new in (replacements or {}).items():
                text = text.replace(old, new)
            data = text.encode("utf-8")
        else:
            data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        else:
            content_type = "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    load_problems()
    port = int(os.environ.get("PORT", "8000"))
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("HOST", default_host)
    server = ThreadingHTTPServer((host, port), AppHandler)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Server running at http://{display_host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
