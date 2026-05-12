# DuhDecoder

A minimal LeetCode-style coding practice app with:

- a Python backend
- a plain HTML/CSS/JS frontend
- Python 3 code execution
- test case validation with pass/fail feedback
- file-backed Python problems in `data/problems.json`

## Run locally

1. Make sure `python3` is installed.
2. Start the server:

```bash
python3 server.py
```

3. Open `http://127.0.0.1:8000`

## Notes

- Built-in problems are simple bug-fix exercises.
- Problems are loaded from `data/problems.json`.
- Admins add or edit problems directly in `data/problems.json`.
- User code runs in a subprocess with a 3-second timeout.
- It is fine for demos, but arbitrary public code execution is not secure enough for a serious production app.

## Problem format

Add problems in `data/problems.json` using JSON like this:

```json
[
  { "input": ["abc"], "output": "cba" },
  { "input": ["racecar"], "output": "racecar" }
]
```

Each `input` must be a JSON array because the app passes it into your function as arguments.

## Deployment

This app is ready for a simple Render deploy.

### Render

1. Push this project to GitHub.
2. Sign in to Render and create a new Web Service from that repo.
3. Render can read the included `render.yaml`, or you can set these manually:

```text
Runtime: Python
Build Command: python -m py_compile server.py
Start Command: python server.py
```

4. After deploy, open your public `onrender.com` URL.

### Important caution

This app runs user-submitted Python code on the server. That is acceptable for a hobby demo, but it is not a safe architecture for a serious public coding platform. For a safer production version, use isolated code runners, rate limiting, auth, and stronger sandboxing.

## Adding more Python problems

For now, editing `data/problems.json` and redeploying is the admin workflow.

Each problem should include:

- `id`
- `title`
- `difficulty`
- `description`
- `starter_code`
- `function_name`
- `mode`
- `samples`
- `tests`
