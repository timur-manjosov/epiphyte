# Epiphyte 🌱

**A Discord bot that grows a single living plant from your channel's activity.**

Every message waters the plant; silence lets it wither over days. Epiphyte is
not a utility bot — it is a small art project with an honest side effect: the
plant shows, unvarnished, how alive a channel really is.

<p align="center">
  <img src="assets/growth.gif" alt="A plant accumulating from a sprout into a branching tree" width="320">
</p>

## What it is, and why

Give Epiphyte one channel and it renders **one plant** for that server. People
talking keeps it lush; a quiet channel lets it dry out and wither. Nothing to
click, nothing to maintain — the plant simply mirrors the room.

The catch that makes it honest: you cannot fake a thriving plant. A single
person spamming the channel hits **diminishing returns** and cannot keep it
alive on their own — only genuine activity from several people can. The plant is
a mirror, not a scoreboard.

Every server gets its own isolated plant — there is no shared, cross-server
world. And no two are alike: each plant grows from its own seed into a body that
accumulates over its whole life, so the same moisture never means the same
shape. A plant *is* its history.

## How it works

- **Watering** — each message in the chosen channel adds a little moisture.
- **Withering** — moisture decays exponentially; left in silence, the plant
  falls from thriving to withered over roughly three days. A *prolonged* drought
  goes further: the outermost branches die back for good, from the tips inward.
- **Growth** — the plant is a persistent, growing body, not a snapshot. On a
  steady heartbeat the bot grows it one step — extending and branching it — and
  what grows *stays*. Moisture sets the pace: a dry plant barely grows, so a full
  tree is the reward of weeks of sustained activity, not a single busy evening.
- **A life of its own** — the plant lives in the channel as a single message the
  bot keeps updated in place. It grows and withers there on its own over days,
  with no command and nobody watching. Growth advances only while the bot is
  running; moisture, by contrast, is decayed exactly across any downtime, so a
  quiet week away still shows.
- **A body that remembers** — vitality and body are separate things. Leaves
  flush on the living tips when moisture is high and fall when it drops, and
  colour and posture follow the mood of the moment — but growth and death are
  permanent. A drought that kills a branch leaves a bare, weathered scar that
  stays legible long after the leaves, and the rest of the plant, have recovered.
- **Individuality** — every server's plant grows from its own random seed: a
  genome fixing its branching angles, bushiness, vigour and foliage, so no two
  servers ever grow the same plant.
- **Fairness** — repeated watering by the same person within a window yields
  progressively less, and growth is gated by moisture, so no one can farm a big
  tree by flooding.
- **Privacy** — the bot only needs to know *that* a message arrived, never
  *what* it said. It reads no message content and requests **no privileged
  gateway intents**.

Same rules, different seeds — four servers' mature plants, each an individual:

![Four different mature plants grown from different seeds](assets/individuals.png)

Vitality plays over a body that keeps the record — lush, then a drought, then
recovered. The leaves return, but the dead branch the drought cost stays as a scar:

![A plant lush, then parched by a drought, then recovered while a dead branch remains as a scar](assets/biography.png)

## Quickstart

You will need Python 3.11+ and a Discord bot token. From an empty server this
takes well under ten minutes.

### 1. Create the bot and get a token

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
   and create a **New Application**.
2. Go to **Bot** and click **Reset Token** to reveal the token. Keep it secret —
   you will pass it to Epiphyte as an environment variable.
3. No privileged intents are required, so leave **Message Content Intent**,
   **Server Members Intent** and **Presence Intent** switched **off**.

### 2. Invite the bot to your server

Under **OAuth2 → URL Generator**, select the scopes `bot` and
`applications.commands`, and the permissions **View Channels**, **Send
Messages**, **Embed Links** and **Attach Files**. Open the generated URL and add
the bot to your server.

Equivalently, use this URL with your application's client id:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot%20applications.commands&permissions=52224
```

### 3. Install and run

```bash
git clone https://github.com/timur-manjosov/epiphyte.git
cd epiphyte

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export EPIPHYTE_TOKEN="your-bot-token"
# Optional: makes slash commands appear instantly in one test server
export EPIPHYTE_GUILD_ID="your-server-id"

python bot.py
```

On first run the bot creates a SQLite file (`epiphyte.db`) in the working
directory to remember each server's plant across restarts.

### 4. Use it in Discord

1. **`/epiphyte-channel #channel`** — choose the channel the plant lives in. The
   bot posts the living plant message there straight away; until this is set,
   messages are ignored.
2. Chat in that channel — every message quietly waters the plant, and it grows
   and withers in the living message on its own over time.
3. **`/plant`** *(optional)* — get a private snapshot of the plant right now, and
   bring the living message back down if it has scrolled out of view.

## Configuration

Epiphyte is configured entirely through environment variables; no secret ever
lives in the code or repository.

| Variable | Required | Purpose |
|---|---|---|
| `EPIPHYTE_TOKEN` | yes | The Discord bot token. |
| `EPIPHYTE_GUILD_ID` | no | A test server id. If set, slash commands appear there instantly; otherwise they are registered globally and can take up to an hour to propagate. |

## Commands

| Command | What it does |
|---|---|
| `/epiphyte-channel #channel` | Choose the channel the plant lives in, and post its living message there. |
| `/plant` | Show a private snapshot now, and re-anchor the living message if it has scrolled away. Never grows the plant — the heartbeat does that. |

## Development

The pure logic — moisture decay and the anti-farming curve (`moisture.py`) and
the plant's genome, accumulating growth and drought dieback (`structure.py`) — is
tested with pytest and depends on neither Discord nor Pillow. Rendering
(`render.py`) is isolated Pillow I/O, and persistence (`storage.py`) is isolated
SQLite I/O.

```bash
pip install -r requirements-dev.txt
pytest              # run the pure-logic tests
python -c "import bot"   # token-free smoke test: the module imports cleanly
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project structure, conventions and
design guidelines.

## Built with

Python, [discord.py](https://github.com/Rapptz/discord.py) (slash commands only,
`discord.Client` + a `CommandTree`), [Pillow](https://python-pillow.org/) for
rendering, [APScheduler](https://github.com/agronholm/apscheduler) for the
metabolic tick, and SQLite from the standard library. Colours follow the
[Nord](https://www.nordtheme.com/) palette.

## License

[MIT](LICENSE) © 2026 Timur Manjosov
