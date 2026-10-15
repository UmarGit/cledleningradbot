"""Offline simulation of the bot with fake Telegram objects."""
import asyncio, os, sys, types, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["BOT_TOKEN"] = "x"
os.environ["DATA_FILE"] = tempfile.mktemp(suffix=".json")
os.environ["TIMEZONE"] = "Europe/Moscow"

import bot, game, content as C
from storage import store

LOG = []

def short(x):
    return str(x).replace("\n", " | ")[:150]

class FakeMsg:
    def __init__(self, chat, text=None, location=None, photo=None, voice=None):
        self.chat_id = chat; self.text = text; self.location = location; self.photo = photo
        self.voice = voice; self.audio = None; self.video_note = None
    async def reply_text(self, t, **k): LOG.append("TEXT: " + short(t) + (f"  [kb]" if k.get("reply_markup") else "")); return self
    async def reply_photo(self, p, caption="", **k): LOG.append("PHOTO: " + short(caption)); return self
    async def reply_document(self, d, filename="", **k): LOG.append(f"DOC: {filename} {len(d)}b"); return self
    async def reply_venue(self, **k): LOG.append(f"VENUE: {k['title']}"); return self
    async def edit_text(self, t, **k): LOG.append("EDIT: " + short(t)); return self
    async def edit_reply_markup(self, *a, **k): return self

class FakeUser:
    def __init__(self, i, name, un): self.id=i; self.full_name=name; self.first_name=name.split()[0]; self.username=un

class FakeQuery:
    def __init__(self, data, msg): self.data=data; self.message=msg
    async def answer(self, t=None, show_alert=False):
        if t: LOG.append(f"ANSWER: {short(t)}")
    async def edit_message_reply_markup(self, *a): pass

class FakeBot:
    username = "sled_demo_bot"
    async def send_message(self, chat, t, **k): LOG.append(f"SEND->{chat}: " + short(t))
    async def send_chat_action(self, *a): pass
    async def send_photo(self, chat, p, caption="", **k): LOG.append(f"SENDPHOTO->{chat}: " + short(caption))

class Ctx:
    def __init__(self): self.user_data = {}; self.args = []; self.bot = FakeBot()

ctxs = {}
def ctx_for(u):
    return ctxs.setdefault(u.id, Ctx())

def upd(u, msg=None, query=None):
    m = msg or (query.message if query else None)
    return types.SimpleNamespace(effective_user=u, effective_message=m, message=m, callback_query=query)

async def say(u, text=None, **kw):
    m = FakeMsg(u.id, text=text, **kw)
    LOG.append(f"\n>> {u.first_name}: {text or list(kw)}")
    await bot.on_message(upd(u, msg=m), ctx_for(u))

async def tap(u, data):
    LOG.append(f"\n>> {u.first_name} taps [{data}]")
    q = FakeQuery(data, FakeMsg(u.id))
    await bot.on_callback(upd(u, query=q), ctx_for(u))

async def cmd(u, fn, args=None):
    c = ctx_for(u); c.args = args or []
    LOG.append(f"\n>> {u.first_name}: /{fn.__name__}")
    await fn(upd(u, msg=FakeMsg(u.id)), c)

Loc = lambda lat, lon: types.SimpleNamespace(latitude=lat, longitude=lon)
Photo = lambda fid: [types.SimpleNamespace(file_id=fid)]

async def main():
    import asyncio as aio
    orig_sleep = aio.sleep
    bot.asyncio.sleep = lambda s: orig_sleep(0)
    anna = FakeUser(1, "Анна Смирнова", "anna")
    ivan = FakeUser(2, "Иван Петров", None)
    await cmd(anna, bot.start)
    await cmd(ivan, bot.start, ["ref_1"])
    await say(anna, bot.B_SEEK)
    await tap(anna, "loc:vyborg_castle")
    await tap(anna, "go:vyborg_castle")
    await say(anna, location=Loc(59.93, 30.36))          # far away
    await say(anna, location=Loc(60.7194, 28.7290))      # on the spot
    await say(anna, "1300")                               # wrong
    await say(anna, "в 1293 году")                        # right
    await tap(anna, "ans:1")                              # wrong quiz
    await tap(anna, "ans:0")                              # right
    await tap(anna, "go:monrepos")
    await tap(anna, "here:monrepos")
    await say(anna, voice=object())
    await tap(anna, "go:gatchina")
    await say(anna, photo=Photo("selfie"))
    await tap(anna, "ans:1")
    await say(anna, photo=Photo("p1"))
    # creator
    await say(anna, bot.B_CREATE)
    await say(anna, location=Loc(60.7100, 28.7500))
    await say(anna, "Дворик с мозаикой")
    await say(anna, photo=Photo("a")); await say(anna, photo=Photo("b"))
    await tap(anna, "c_photos_done")
    await say(anna, "коротко")
    await say(anna, "Тихий двор за аркой: старая мозаика, скамейка и эхо шагов. Лучше всего утром.")
    await say(anna, "Сколько цветов в мозаике над входом?")
    await say(anna, "7")
    await tap(anna, "c_submit")
    # ivan plays anna's trace
    uloc = store.data["locations"][0]["id"]
    await tap(ivan, f"loc:{uloc}")
    await tap(ivan, f"go:{uloc}")
    await tap(ivan, f"here:{uloc}")
    await say(ivan, "семь")
    await say(ivan, "7")
    await say(ivan, bot.B_CERT)
    await cmd(ivan, bot.demo_cmd)
    await say(ivan, bot.B_CERT)
    await say(anna, bot.B_PROFILE)
    await say(anna, bot.B_TOP)
    await say(anna, bot.B_CERT)
    # duplicate trace -> moderation fails
    await say(ivan, bot.B_CREATE)
    await say(ivan, location=Loc(60.7101, 28.7501))
    await say(ivan, "Тот же двор")
    await say(ivan, photo=Photo("z")); await say(ivan, "дальше")
    await say(ivan, "Очень интересное место, тут красиво, рекомендую всем зайти!")
    await say(ivan, "Какого цвета дверь?")
    await say(ivan, "синяя")
    await tap(ivan, "c_submit")
    print("\n".join(LOG))

asyncio.run(main())
