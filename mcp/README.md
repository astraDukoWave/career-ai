# CareerAI MCP server

Use CareerAI from **Claude Code** or **Claude Desktop**: ask Claude to tailor
your CV to a job posting, or to suggest an answer to an interview question,
without leaving your conversation.

The server is a thin local client of the public CareerAI API. The ATS score,
the PDF and the interview suggestion are all computed by the API. The server
reads your profile from a JSON file on your machine, sends it with each
request, and translates the answer for Claude. It holds no API keys.

## Tools

| Tool | What it does |
|---|---|
| `generate_cv(job_posting)` | Tailors your CV to the posting. Returns the role title, the ATS score, matched and missing keywords, and a link to the PDF. |
| `interview_suggestion(question)` | Suggests an answer grounded in your profile. Returns the detected intent (`behavioral_star`, `tech_concept` or `tech_code`), the language and the text. |
| `get_profile()` | Returns your profile exactly as stored in the file. |

### Honesty rules

The server tells Claude, and every tool description repeats it:

- Your profile file is the **only source of facts** about you. Claude must
  not add experience, companies, metrics or skills that are not in it.
- **Missing keywords are gaps**, not claims. Claude presents them as things
  you may confirm, never as things you have done.
- A placeholder such as `[your real example: …]` in a suggestion means your
  profile has no matching story. Fill it with a real one, or leave it out.

## Install

You need Python 3.10 or newer (`python3 --version`) and a clone of this
repo. A dedicated virtual environment keeps the install isolated and gives
you an absolute path that both Claude clients can run:

```bash
cd path/to/career-ai
python3 -m venv ~/.careerai-mcp
~/.careerai-mcp/bin/pip install -e mcp
~/.careerai-mcp/bin/careerai-mcp --check   # prints the three tools
```

### Your profile

```bash
cp mcp/profile.example.json ~/careerai-profile.json
```

Edit `~/careerai-profile.json` with your real, verifiable facts. It has the
same shape as the profile in the web app: `name` is required, and at most 3
roles go in `experience`. Keep it **outside the repo**. Never commit it;
`careerai-profile.json` is in `.gitignore` as a safety net.

### Claude Code

```bash
claude mcp add careerai --scope user --transport stdio \
  -e CAREERAI_PROFILE="$HOME/careerai-profile.json" \
  -- "$HOME/.careerai-mcp/bin/careerai-mcp"
```

The name goes first. `-e`/`--env` takes several values, so if it came
before the name it would take `careerai` as one more variable and the add
would fail. The `--` separates the command.
`claude mcp get careerai` (or `/mcp` inside Claude Code) shows the server as
connected. Then ask, for example: *"Use careerai to generate my CV for this
job posting: …"*.

### Claude Desktop (macOS)

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`
and restart Claude Desktop. Use absolute paths, because the file does not
expand `~` or `$HOME`:

```json
{
  "mcpServers": {
    "careerai": {
      "command": "/Users/YOUR_USER/.careerai-mcp/bin/careerai-mcp",
      "env": { "CAREERAI_PROFILE": "/Users/YOUR_USER/careerai-profile.json" }
    }
  }
}
```

## Configuration

Environment variables only:

| Variable | Default | Purpose |
|---|---|---|
| `CAREERAI_PROFILE` | none (required) | Path to your profile JSON. |
| `CAREERAI_API_URL` | the live demo URL | Point it to `http://localhost:8000` to use a local backend. |

## Privacy

- Each call sends your profile and the posting or question to the CareerAI
  API, the same data the web app sends. The API uses Google Gemini to
  process it.
- The server stores nothing and does not log profile content. Validation
  errors list only the invalid field names.

## Troubleshooting

- **A call fails with a 5xx or a timeout.** The API may be restarting (after
  a deploy, or Heroku's daily restart) or Gemini may be busy. Retry in a
  minute. Calls time out after 60 s (`generate_cv`) and 40 s
  (`interview_suggestion`), with no automatic retries.
- **"CareerAI rejected the request (422)".** The message names the invalid
  fields. Compare your file with `profile.example.json`.
- **"CAREERAI_PROFILE is not set" or "Profile file not found".** Fix the
  path in the `--env` flag or in the Desktop config.

## Uninstall

```bash
claude mcp remove --scope user careerai
rm -rf ~/.careerai-mcp
```

For Claude Desktop, delete the `careerai` entry from the config file.

## Development

```bash
cd mcp
pip install -e ".[test]"
python -m pytest
```

The tests need neither network nor API keys. They mock HTTP with
`httpx.MockTransport`, run a real stdio session, and validate every request
body against the API's Pydantic schemas in `backend/app/schemas/`. A change
to those schemas must be mirrored in `careerai_mcp/server.py`, the same rule
as `frontend/src/api/client.ts`.
