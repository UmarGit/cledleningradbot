# «След» Telegram bot (demo)

A demo quest bot for the Leningrad Region project.

- **Искатель (Seeker):** the player picks a location and confirms the visit with GPS or a selfie. They then solve a task (a text answer, a quiz, a voice message or a photo) and earn XP and achievements.
- **Созидатель (Creator):** the player adds a new place with geolocation, 1–3 photos, a description and a task. It passes a mock moderation check and then appears for everyone with the author's name.
- **Rewards:** the bot has levels, 9 achievements, a leaderboard and referral links. Players can download a PNG + PDF **certificate** once they reach `CERT_MIN_XP`.

## Run on a server (5 minutes)

```bash
# 1. Create a bot with @BotFather and copy the token
cd sled-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # put BOT_TOKEN (and your ADMIN_IDS) inside
python bot.py
```

The bot uses long polling, so it needs no domain, webhook or open ports.

**Keep it running:** use `sled-bot.service` (systemd; instructions are inside the file) or Docker:

```bash
docker build -t sled-bot .
docker run -d --restart=always --env-file .env -v $PWD/data:/app/data --name sled-bot sled-bot
```

## Check it without Telegram

```bash
python tests/simulate.py
```

This plays a full scenario with fake users: a referral, three quests, adding a trace, another player completing that trace, the certificate, and a duplicate trace being rejected. It prints the whole dialogue.

## Demo tips

- `DEMO_MODE=1` adds a **🧪 «Я на месте (демо)»** button, so the audience can play from the room. It also enables `/demo`, which gives +200 XP so the certificate opens instantly.
- `/reset` wipes your progress, so you can show the flow again from the start.
- A real GPS check works too: send your location and the bot shows the distance to the point. The visit counts within `VISIT_RADIUS_M` metres.
- `MODERATION=manual` sends new traces to `ADMIN_IDS` with Approve / Reject buttons.

## Rules ("conditions") you can tune

| Where | What |
|---|---|
| `content.py` → `LOCATIONS` | Places, coordinates, hints, tasks (`input`, `quiz`, `voice`, `photo`) |
| `content.py` → XP constants | First-try bonus +20, speed bonus +10 (≤ 20 s), −10 per mistake (at most half the task's XP), +100 for a new trace, +30 per invited friend, +10 to the author each time someone completes their trace |
| `content.py` → `LEVELS` | Новичок 0 → Путник 100 → Следопыт 250 → Краевед 500 → Хранитель следов 900 |
| `content.py` → `ACHIEVEMENTS` | Первый след, Исследователь (3 quests), Созидатель, Снайпер (3 first-try answers in a row), Молния, Ночной странник (22:00–05:00), Полиглот, Душа компании, Вдохновитель |
| `game.py` → `moderate()` | Mock moderation checks: has photos, description ≥ 40 characters, no ads or links, no other trace within 150 m |
| `certificate.py` | Certificate layout (Inter font, brand cyan) |

Replaying a completed quest gives 25% XP. Data is stored in `data/db.json`, which is fine for a demo. For a real launch, switch to SQLite or Postgres.

The location facts in `content.py` are demo content. Double-check them before a public launch.
