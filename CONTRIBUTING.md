# Contributing to Epiphyte

Thanks for considering a contribution. Epiphyte is a small art project, and its
code is meant to stay small and legible. This guide explains how it is built and
what to keep in mind when changing it.

## The guiding principle: the razor

When a change can be built in more than one way, **build the simplest structure
that correctly expresses the idea at hand.** No abstraction, no configurability,
no library added "for later" until the need is real. In case of doubt, the
simpler solution wins — this is the tie-breaker, not a reason to stall.

Concretely, this means we do *not* add abstraction layers, plugin systems,
configuration frameworks, or dependencies in anticipation of features that do
not exist yet.

## Project structure

The core discipline is a clean split between **pure logic** and **I/O**.

| File | Role | Depends on |
|---|---|---|
| `moisture.py` | **Pure logic** — moisture decay and the anti-farming curve. | nothing but the stdlib |
| `structure.py` | **Pure logic** — the plant's genome, its accumulating seeded growth, and drought dieback. | nothing but the stdlib |
| `render.py` | **I/O** — draws a structure into a PNG, with vitality modulating foliage, colour and posture. | Pillow |
| `storage.py` | **I/O** — SQLite persistence of per-guild state. | stdlib `sqlite3` |
| `bot.py` | **Thin adapter** — Discord client, slash commands, events, and the metabolic tick that grows and re-renders each plant; wires the above together. | discord.py, APScheduler |
| `tests/` | pytest suite for the **pure logic only**. | pytest |

### Pure logic ⟷ I/O — the heart of the design

- **Pure functions** (`moisture.py`, `structure.py`) are deterministic, have no
  side effects, and contain **no `import discord`** and no Pillow. Same input,
  same output. They never read the clock — elapsed time and timestamps are
  passed in.
- **`bot.py` is a thin adapter**: it receives events, calls the pure logic, and
  sends the result to Discord. It holds no meaningful computation of its own.
- **`render.py`** and **`storage.py`** isolate the two kinds of I/O (drawing and
  persistence) so the pure logic never touches either.

The payoff: the interesting parts are testable with pytest without ever starting
Discord.

## Architecture invariants (non-negotiable)

- **Secrets only via environment variables** (`EPIPHYTE_TOKEN`,
  `EPIPHYTE_GUILD_ID`) — never in code or the repository.
- **No privileged gateway intents**, and never read message content. The bot
  only needs to know *that* a message arrived. `discord.Intents.default()` is
  enough.
- **Slash commands only**, via `discord.Client` with a `CommandTree` — not
  `commands.Bot`. Watering is always passive, never a command.
- **Pure logic imports neither `discord` nor Pillow.** Keep computation out of
  `bot.py`.
- **Add a dependency only when the code actually needs it.**

## Conventions

- **Language: everything committed is English** — identifiers, comments,
  docstrings, log messages, all user-facing bot text, documentation, and commit
  messages.
- **Style:** PEP 8, full type hints, and docstrings for every module, class and
  public function. Keep functions small and focused on one responsibility.
- **Don't reformat or rewrite** untouched code you aren't changing.
- **Colours** follow the [Nord](https://www.nordtheme.com/) palette; reuse the
  constants in `render.py` rather than introducing new colours.

## Running the tests

Tests cover the **pure logic only**, never the Discord integration.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                  # run the pure-logic tests
python -c "import bot"   # token-free smoke test: the module must import cleanly
```

Please keep the suite green, and add tests for any new pure logic you write.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
  `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Split changes into meaningful,
  self-contained commits.
- Keep the README truthful: document only what already exists, never features
  that are merely planned.
- Before opening a pull request, run the tests and the smoke test, and describe
  what changed and why.

Small, sharp, and honest — that's the whole idea. Welcome aboard. 🌱
