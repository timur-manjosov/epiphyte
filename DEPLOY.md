# Deploying Epiphyte

Epiphyte runs as a single isolated container, one per project, matching the
rest of the server's infra. This covers bringing it up; the container is
outbound-only (it just holds a Discord gateway connection), so there is
nothing to reverse-proxy and no ports to publish.

## 1. Get the code onto the server

```bash
git clone https://github.com/timur-manjosov/epiphyte.git ~/projects/epiphyte
cd ~/projects/epiphyte
```

## 2. Create `.env`

Not committed to git — create it directly on the server:

```bash
cat > .env <<'EOF'
EPIPHYTE_TOKEN=your-bot-token
EOF
```

`EPIPHYTE_GUILD_ID` is optional (only useful for instant command sync in a
single test server) and can be added the same way if needed.

## 3. Bring the container up

The bot runs as a non-root user (uid 1000) inside the container, so the
bind-mounted data directory needs to be writable by that uid:

```bash
mkdir -p data
chown 1000:1000 data
```

```bash
docker compose build
docker compose up -d
```

The plant's SQLite state (`epiphyte.db` plus its `-wal`/`-shm` sidecars) lives
in `./data/`, bind-mounted into the container, so it survives rebuilds and
restarts and is covered by the existing restic backup job as-is.

## 4. Check it came up

```bash
docker compose logs -f
```

Look for discord.py logging in as ready. `Ctrl-C` to stop following (the
container keeps running).

## Restarting / updating

```bash
git pull
docker compose build
docker compose up -d
```

`restart: unless-stopped` means the container also comes back on its own if
it crashes or the host reboots.
