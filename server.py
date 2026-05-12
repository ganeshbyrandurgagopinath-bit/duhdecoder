import json
import os
import subprocess
import sys
import tempfile
import textwrap
from copy import deepcopy
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PROBLEMS_FILE = Path(os.environ.get("PROBLEMS_FILE", DATA_DIR / "problems.json"))
MAX_REQUEST_BYTES = 100_000

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

    def do_GET(self):
        if self.path == "/healthz":
            return self._send_json({"ok": True, "problem_count": len(PROBLEMS)})
        if self.path == "/api/problems":
            return self._send_json([serialize_problem(problem) for problem in PROBLEMS])
        if self.path.startswith("/api/problems/"):
            problem_id = self.path.rsplit("/", 1)[-1]
            problem = PROBLEM_INDEX.get(problem_id)
            if not problem:
                return self._send_json(
                    {"error": "Problem not found."}, status=HTTPStatus.NOT_FOUND
                )
            return self._send_json(serialize_problem(problem))
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

        if self.path == "/api/run":
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
