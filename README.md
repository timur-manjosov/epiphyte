# Epiphyte 🌱

**A Discord bot that grows a single living plant from your server's activity.**

Every message anywhere in the server waters the plant; silence lets it wither
over days. Epiphyte is not a utility bot — it is a small art project with an
honest side effect: the plant shows, unvarnished, how alive a server really is.

<p align="center">
  <img src="assets/growth.gif" alt="A plant accumulating from a sprout into a branching tree" width="320">
</p>

## What it is, and why

Epiphyte renders **one plant** for the whole server, displayed in whichever
channel you choose. People talking anywhere in the server keeps it lush; a
quiet server lets it dry out and wither. Nothing to click, nothing to
maintain — the plant simply mirrors the room.

The catch that makes it honest: you cannot fake a thriving plant. A single
person spamming hits **diminishing returns** and cannot keep it alive on their
own — only genuine activity from several people can. The plant is a mirror,
not a scoreboard.

Every server gets its own isolated plant — there is no shared, cross-server
world. And no two are alike: each plant grows from its own seed into a body that
accumulates over its whole life, so the same moisture never means the same
shape. A plant *is* its history — and a server that stays alive for months will
see things a busy weekend can never buy: a bloom, a seed, eventually an epiphyte
of its own.

## How it works

- **Watering** — each message anywhere in the server adds a little moisture.
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
- **Flowering** — kept genuinely healthy for weeks on end, the plant banks that
  health and eventually comes into bloom, in a colour its own genome decides.
  Flowering then spends the very reserve it took to get there, so the bloom fades
  by itself and the next one has to be earned again: a season, not a switch. A
  bloom that lasts long enough sets seed, and those pale seed heads stay on the
  body long after the flowers are gone.
- **An epiphyte of its own** — a tree that has grown very old and very large and
  flowered several times over can take on the thing this project is named after: a
  second, far smaller plant that settles on one of its old limbs and grows there,
  with a seed and a dwarfed genome of its own. It cannot be hurried.
- **Death and lineage** — abandon a server for long enough and even the inner
  wood dies: the plant dies, lingers a while as a bare grey skeleton, then a new
  seed sprouts in its place. That seed is a mutation of the one before, so each
  generation resembles its parent yet is its own individual, and a plant that
  lived to set seed hands on a richer line. There is no final state — the line
  simply continues.
- **Individuality** — every server's plant grows from its own random seed: a
  genome fixing its branching angles, bushiness, vigour, foliage and the colour it
  flowers in, so no two servers ever grow the same plant, and a seed carries those
  traits to its heirs.
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

And when neglect is total, the plant dies — then a mutated successor grows in its
place, a recognisable but distinct next generation:

![A plant thriving, then dead and grey, then its grown successor resembling it](assets/lineage.png)

At the other end of a life, the rare states have to be earned. Weeks of real health
bring the plant into bloom; the flowering spends that health and fades again, but
the seed it set stays on the bare branches:

![A tended plant, the same plant in blue blossom, and the same plant parched with only pale seed heads left](assets/bloom.png)

And the rarest of them, on a tree grown old and large and flowered many times over:
its own epiphyte, a second little organism living on one of its limbs.

![An old spreading tree carrying a small blue-green epiphyte, and a close-up of that epiphyte on its branch](assets/epiphyte.png)

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

1. **`/epiphyte-channel #channel`** — choose the channel the plant is displayed
   in. The bot posts the living plant message there straight away; until this is
   set, messages are ignored.
2. Chat anywhere in the server — every message quietly waters the plant, and it
   grows and withers in the living message on its own over time.
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
| `/epiphyte-channel #channel` | Choose the channel the plant is displayed in, and post its living message there. |
| `/plant` | Show a private snapshot now, and re-anchor the living message if it has scrolled away. Never grows the plant — the heartbeat does that. |

## Development

The pure logic — moisture decay and the anti-farming curve (`moisture.py`) and
the plant's genome, growth, dieback, lifecycle and milestones (`structure.py`) —
is tested with pytest and depends on neither Discord nor Pillow. Rendering (`render.py`) is
isolated Pillow I/O, and persistence (`storage.py`) is isolated SQLite I/O.

```bash
pip install -r requirements-dev.txt
pytest              # run the pure-logic tests
python -c "import bot"   # token-free smoke test: the module imports cleanly
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project structure, conventions and
design guidelines.

## Deployment

A `Dockerfile` and `docker-compose.yml` are included for running Epiphyte as a
container. See [DEPLOY.md](DEPLOY.md) for the exact steps.

## Built with

Python, [discord.py](https://github.com/Rapptz/discord.py) (slash commands only,
`discord.Client` + a `CommandTree`), [Pillow](https://python-pillow.org/) for
rendering, [APScheduler](https://github.com/agronholm/apscheduler) for the
metabolic tick, and SQLite from the standard library. Colours follow the
[Nord](https://www.nordtheme.com/) palette.

## License

[MIT](LICENSE) © 2026 Timur Manjosov
