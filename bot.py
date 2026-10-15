"""«След» — demo Telegram bot.

Seekers pick a location, confirm the visit (GPS or selfie), solve a task and earn XP + achievements.
Creators add their own locations ("Оставить след"), which pass mock moderation and appear for everyone.
Players can download a certificate (PNG + PDF) once they reach CERT_MIN_XP.

Run:  python bot.py   (needs BOT_TOKEN in .env)
"""
import asyncio
import html
import logging
import time

from telegram import (
    InlineKeyboardButton as IB,
    InlineKeyboardMarkup as IKM,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import certificate
import config
import content as C
import game
from storage import store

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("sled")

H = ParseMode.HTML
e = html.escape

# ---------- keyboards ----------
B_SEEK = "🔍 Искать следы"
B_CREATE = "👣 Оставить след"
B_PROFILE = "👤 Профиль"
B_TOP = "🏆 Рейтинг"
B_CERT = "📜 Сертификат"
B_INVITE = "🤝 Пригласить друга"
B_CANCEL = "❌ Отмена"
B_SEND_GEO = "📍 Отправить геолокацию"

MAIN_KB = ReplyKeyboardMarkup(
    [[B_SEEK, B_CREATE], [B_PROFILE, B_TOP], [B_CERT, B_INVITE]], resize_keyboard=True
)
GEO_KB = ReplyKeyboardMarkup(
    [[KeyboardButton(B_SEND_GEO, request_location=True)], [B_CANCEL]], resize_keyboard=True
)
CANCEL_KB = ReplyKeyboardMarkup([[B_CANCEL]], resize_keyboard=True)


def reset_mode(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("mode", "quest", "draft"):
        ctx.user_data.pop(k, None)


def author_line(loc: dict) -> str:
    a = loc.get("author")
    if not a:
        return ""
    who = f"@{a['username']}" if a.get("username") else e(a["name"])
    return f"\n✍️ Автор следа: {who}"


async def announce(update: Update, user: dict, new_ach: list[str], level_up: bool) -> None:
    """Fun notifications for achievements and level-ups."""
    msg = update.effective_message
    for key in new_ach:
        em, name, desc = C.ACHIEVEMENTS[key]
        await msg.reply_text(f"{em} <b>Новая ачивка: {name}</b>\n<i>{desc}</i>", parse_mode=H)
    if level_up:
        lvl, name, _ = game.level_of(user["xp"])
        await msg.reply_text(f"🎉 <b>Новый уровень {lvl}: {name}!</b>", parse_mode=H)


# ---------- start / help ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    is_new = store.get_user(tg.id) is None
    user = store.user(tg)
    reset_mode(ctx)

    # referral: /start ref_<id>
    if is_new and ctx.args and ctx.args[0].startswith("ref_"):
        try:
            inviter_id = int(ctx.args[0][4:])
        except ValueError:
            inviter_id = None
        inviter = store.get_user(inviter_id) if inviter_id else None
        if inviter and inviter_id != tg.id:
            user["invited_by"] = inviter_id
            inviter["invites"] += 1
            game.add_xp(inviter, C.XP_INVITE)
            got = game.grant(inviter, "friend")
            text = f"🤝 По твоей ссылке пришёл {e(tg.full_name)}! +{C.XP_INVITE} XP"
            if got:
                text += "\n🤝 <b>Новая ачивка: Душа компании</b>"
            try:
                await ctx.bot.send_message(inviter_id, text, parse_mode=H)
            except Exception:  # inviter blocked the bot etc.
                pass
    store.save()

    caption = (
        f"Привет, {e(tg.first_name or 'путник')}! 👋\n\n"
        "<b>След</b>: квест по местам Ленинградской области, которых нет в путеводителях.\n\n"
        "🔍 <b>Искатель</b> проходит квесты: приходит на точку, разгадывает задание, получает XP и ачивки.\n"
        "👣 <b>Созидатель</b> оставляет свой след: добавляет новое место на общую карту.\n\n"
        "Можно совмещать обе роли. С чего начнём?"
    )
    logo = config.ASSETS / "logo_card.png"
    if logo.exists():
        await update.message.reply_photo(logo.open("rb"), caption=caption, parse_mode=H, reply_markup=MAIN_KB)
    else:
        await update.message.reply_text(caption, parse_mode=H, reply_markup=MAIN_KB)


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Команды</b>\n"
        "/start · главное меню\n/profile · профиль\n/top · рейтинг\n/cert · сертификат\n"
        "/cancel · отменить текущее действие\n/reset · начать игру заново"
    )
    if config.DEMO_MODE:
        text += "\n/demo · 🧪 +200 XP для демонстрации"
    await update.message.reply_text(text, parse_mode=H, reply_markup=MAIN_KB)


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    reset_mode(ctx)
    await update.effective_message.reply_text("Окей, отменили. Что дальше?", reply_markup=MAIN_KB)


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    store.data["users"].pop(str(update.effective_user.id), None)
    store.save()
    reset_mode(ctx)
    await update.message.reply_text("🔄 Прогресс сброшен. Жми /start", reply_markup=MAIN_KB)


async def demo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    if not (config.DEMO_MODE or tg.id in config.ADMIN_IDS):
        return
    user = store.user(tg)
    _, up = game.add_xp(user, 200)
    store.save()
    await update.message.reply_text(f"🧪 Демо-бонус: +200 XP. Теперь у тебя {user['xp']} XP.")
    await announce(update, user, [], up)


# ---------- seeker: list & card ----------
def locations_kb(user: dict) -> IKM:
    rows = []
    for loc in game.all_locations():
        mark = " ✓" if loc["id"] in user["done"] else ""
        rows.append([IB(f"{loc['emoji']} {loc['title']} · {loc['place']}{mark}", callback_data=f"loc:{loc['id']}")])
    rows.append([IB("📍 Показать ближайшие ко мне", callback_data="near")])
    return IKM(rows)


async def seek(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    reset_mode(ctx)
    user = store.user(update.effective_user)
    done, total = len(user["done"]), len(game.all_locations())
    await update.effective_message.reply_text(
        f"🗺 <b>Куда отправимся?</b>\nПройдено {done} из {total} следов.",
        parse_mode=H,
        reply_markup=locations_kb(user),
    )


async def show_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE, loc_id: str) -> None:
    loc = game.get_location(loc_id)
    q = update.callback_query
    if not loc:
        await q.answer("Локация не найдена", show_alert=True)
        return
    user = store.user(update.effective_user)
    types = {"input": "✏️", "quiz": "❓", "voice": "🗣", "photo": "📸"}
    tasks = " ".join(types[t["type"]] for t in loc["tasks"])
    status = "\n✅ Ты уже проходил этот след (повтор = 25% XP)" if loc_id in user["done"] else ""
    text = (
        f"{loc['emoji']} <b>{e(loc['title'])}</b>\n📍 {e(loc['place'])}\n\n{e(loc['intro'])}\n\n"
        f"Задания: {tasks}\nНаграда: до <b>{loc['xp'] + C.XP_FIRST_TRY_BONUS * len(loc['tasks'])} XP</b>"
        f"{author_line(loc)}{status}"
    )
    kb = IKM([[IB("▶️ Начать квест", callback_data=f"go:{loc_id}")], [IB("⬅️ Ко всем следам", callback_data="list")]])
    if loc.get("photos"):
        await q.message.reply_photo(loc["photos"][0], caption=text, parse_mode=H, reply_markup=kb)
    else:
        await q.message.reply_text(text, parse_mode=H, reply_markup=kb)


async def start_quest(update: Update, ctx: ContextTypes.DEFAULT_TYPE, loc_id: str) -> None:
    loc = game.get_location(loc_id)
    msg = update.effective_message
    ctx.user_data["mode"] = "visit"
    ctx.user_data["quest"] = {"loc": loc_id, "task": 0, "attempts": 0, "started": time.time(), "earned": 0}
    if loc.get("lat") is not None:
        await msg.reply_venue(latitude=loc["lat"], longitude=loc["lon"], title=loc["title"], address=loc["place"])
    kb = IKM([[IB("🧪 Я на месте (демо)", callback_data=f"here:{loc_id}")]]) if config.DEMO_MODE else None
    await msg.reply_text(
        f"🧭 <b>Квест начался!</b>\n💡 Подсказка: {e(loc['hint'])}\n\n"
        "Когда будешь на месте, подтверди визит: отправь <b>геолокацию</b> или <b>селфи</b> на фоне места.",
        parse_mode=H,
        reply_markup=GEO_KB,
    )
    if kb:
        await msg.reply_text("Для демонстрации можно пропустить дорогу 👇", reply_markup=kb)


async def visit_confirmed(update: Update, ctx: ContextTypes.DEFAULT_TYPE, how: str) -> None:
    ctx.user_data["mode"] = "task"
    await update.effective_message.reply_text(f"✅ Визит подтверждён ({how}). Поехали!", reply_markup=MAIN_KB)
    await send_task(update, ctx)


# ---------- seeker: tasks ----------
async def send_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    qs = ctx.user_data["quest"]
    loc = game.get_location(qs["loc"])
    task = loc["tasks"][qs["task"]]
    qs["attempts"], qs["t0"] = 0, time.time()
    n, total = qs["task"] + 1, len(loc["tasks"])
    head = f"<b>Задание {n}/{total}</b>\n"
    msg = update.effective_message
    if task["type"] == "quiz":
        kb = [[IB(opt, callback_data=f"ans:{i}")] for i, opt in enumerate(task["options"])]
        await msg.reply_text(head + e(task["q"]), parse_mode=H, reply_markup=IKM(kb))
    else:
        tail = {
            "input": "\n\n✏️ Напиши ответ сообщением.",
            "voice": "\n\n🎙 Отправь голосовое сообщение.",
            "photo": "\n\n📸 Отправь фото.",
        }[task["type"]]
        kb = IKM([[IB("💡 Подсказка", callback_data="hint")]]) if task.get("hint") else None
        await msg.reply_text(head + e(task["q"]) + tail, parse_mode=H, reply_markup=kb)


async def task_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE, correct: bool) -> None:
    qs = ctx.user_data["quest"]
    loc = game.get_location(qs["loc"])
    task = loc["tasks"][qs["task"]]
    user = store.user(update.effective_user)
    msg = update.effective_message
    qs["attempts"] += 1

    if not correct:
        hint = f"\n💡 {e(task['hint'])}" if task.get("hint") and qs["attempts"] >= 1 else ""
        lines = ["Почти! Попробуй ещё раз 🙂", "Не то. Подумай ещё 🤔", "Мимо, но ты близко!"]
        await msg.reply_text(lines[(qs["attempts"] - 1) % 3] + hint, parse_mode=H)
        return

    seconds = time.time() - qs["t0"]
    share = loc["xp"] // len(loc["tasks"])
    xp, notes = game.task_xp(share, qs["attempts"], seconds)
    replay = loc["id"] in user["done"]
    if replay:
        xp = max(1, xp // 4)
        notes = ["повтор: 25% XP"]
    _, up = game.add_xp(user, xp)
    qs["earned"] += xp
    new = [] if replay else game.after_task(user, qs["attempts"], seconds, task["type"])
    store.save()
    praise = ["Верно!", "Точно!", "Блестяще!", "В яблочко!"][qs["task"] % 4]
    await msg.reply_text(f"✅ <b>{praise}</b> +{xp} XP\n<i>{', '.join(notes)}</i>", parse_mode=H)
    await announce(update, user, new, up)

    qs["task"] += 1
    if qs["task"] < len(loc["tasks"]):
        await send_task(update, ctx)
    else:
        await finish_quest(update, ctx, user, loc, replay)


async def finish_quest(update, ctx, user: dict, loc: dict, replay: bool) -> None:
    earned = ctx.user_data["quest"]["earned"]
    reset_mode(ctx)
    new = []
    if not replay:
        user["done"].append(loc["id"])
        new = game.after_quest(user)
        a = loc.get("author")
        if a and a["id"] != user["id"]:
            author = store.get_user(a["id"])
            if author:
                game.add_xp(author, C.XP_AUTHOR_ROYALTY)
                got = game.grant(author, "inspirer")
                note = f"✨ Твой след «{e(loc['title'])}» прошёл {e(user['name'])}! +{C.XP_AUTHOR_ROYALTY} XP"
                if got:
                    note += "\n✨ <b>Новая ачивка: Вдохновитель</b>"
                try:
                    await ctx.bot.send_message(a["id"], note, parse_mode=H)
                except Exception:
                    pass
    store.save()
    lvl, name, nxt = game.level_of(user["xp"])
    left = f"до следующего уровня {nxt - user['xp']} XP" if nxt else "максимальный уровень"
    kb = [[IB("🗺 Следующий след", callback_data="list")]]
    if user["xp"] >= config.CERT_MIN_XP:
        kb.append([IB("📜 Получить сертификат", callback_data="cert")])
    await update.effective_message.reply_text(
        f"🏁 <b>Квест «{e(loc['title'])}» пройден!</b>\n\n"
        f"За квест: <b>+{earned} XP</b>\nВсего: {user['xp']} XP · уровень {lvl} «{name}»\n"
        f"{game.progress_bar(user['xp'])} {left}",
        parse_mode=H,
        reply_markup=IKM(kb),
    )
    await announce(update, user, new, False)


# ---------- creator flow ----------
STEPS = 6


async def create_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    reset_mode(ctx)
    store.user(update.effective_user)
    ctx.user_data["mode"] = "c_loc"
    ctx.user_data["draft"] = {"photos": []}
    await update.effective_message.reply_text(
        "👣 <b>Оставь свой след</b>\nНашёл интересное, малоизвестное или уединённое место? Добавь его на общую карту!\n\n"
        f"<b>Шаг 1/{STEPS}.</b> Отправь геолокацию места (или напиши адрес).",
        parse_mode=H,
        reply_markup=GEO_KB,
    )


async def creator_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles one creator step. Returns True if the message was consumed."""
    mode = ctx.user_data.get("mode", "")
    if not mode.startswith("c_"):
        return False
    msg = update.effective_message
    d = ctx.user_data["draft"]
    text = (msg.text or "").strip()

    if mode == "c_loc":
        if msg.location:
            d["lat"], d["lon"], d["address"] = msg.location.latitude, msg.location.longitude, None
        elif len(text) >= 5:
            d["lat"] = d["lon"] = None
            d["address"] = text
        else:
            await msg.reply_text("Нужна геолокация (кнопка ниже) или адрес текстом.")
            return True
        ctx.user_data["mode"] = "c_title"
        await msg.reply_text(f"<b>Шаг 2/{STEPS}.</b> Как называется место? Коротко, до 60 символов.", parse_mode=H, reply_markup=CANCEL_KB)

    elif mode == "c_title":
        if not 3 <= len(text) <= 60:
            await msg.reply_text("Название должно быть от 3 до 60 символов.")
            return True
        d["title"] = text
        ctx.user_data["mode"] = "c_photos"
        await msg.reply_text(f"<b>Шаг 3/{STEPS}.</b> Пришли 1–3 фотографии места 📸", parse_mode=H)

    elif mode == "c_photos":
        if not msg.photo:
            if d["photos"]:
                return await photos_done(update, ctx)
            await msg.reply_text("Жду хотя бы одно фото 📸")
            return True
        d["photos"].append(msg.photo[-1].file_id)
        n = len(d["photos"])
        if n >= 3:
            return await photos_done(update, ctx)
        await msg.reply_text(
            f"Фото {n}/3 ✓", reply_markup=IKM([[IB("Готово ➡️", callback_data="c_photos_done")]])
        )

    elif mode == "c_desc":
        if len(text) < 40:
            left = 40 - len(text)
            await msg.reply_text(f"Расскажи чуть подробнее: ещё {left} {game.plural(left, 'символ', 'символа', 'символов')} 🙂")
            return True
        d["desc"] = text
        ctx.user_data["mode"] = "c_q"
        await msg.reply_text(
            f"<b>Шаг 5/{STEPS}.</b> Придумай задание для других игроков.\n"
            "Например: «Сколько окон на фасаде?» или «Какое животное изображено на гербе?»",
            parse_mode=H,
        )

    elif mode == "c_q":
        if len(text) < 8:
            await msg.reply_text("Вопрос слишком короткий.")
            return True
        d["question"] = text
        ctx.user_data["mode"] = "c_a"
        await msg.reply_text(f"<b>Шаг 6/{STEPS}.</b> Какой правильный ответ? Одно слово или число.", parse_mode=H)

    elif mode == "c_preview":
        await msg.reply_text("Нажми кнопку под карточкой: отправить на модерацию или заполнить заново 👆")

    elif mode == "c_a":
        if not text:
            return True
        d["answer"] = text
        ctx.user_data["mode"] = "c_preview"
        await send_preview(update, ctx)
    return True


async def photos_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    ctx.user_data["mode"] = "c_desc"
    await update.effective_message.reply_text(
        f"<b>Шаг 4/{STEPS}.</b> Опиши место: почему оно интересное, чем там заняться, какая атмосфера? (от 40 символов)",
        parse_mode=H,
    )
    return True


def draft_caption(d: dict, user: dict) -> str:
    where = e(d["address"]) if d.get("address") else f"{d['lat']:.4f}, {d['lon']:.4f}"
    who = f"@{user['username']}" if user.get("username") else e(user["name"])
    return (
        f"📍 <b>{e(d['title'])}</b>\n<i>{where}</i>\n\n{e(d['desc'])}\n\n"
        f"❓ {e(d['question'])}\n\n✍️ Автор следа: {who}"
    )


async def send_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    d = ctx.user_data["draft"]
    user = store.user(update.effective_user)
    kb = IKM(
        [
            [IB("🚀 Отправить на модерацию", callback_data="c_submit")],
            [IB("✏️ Заново", callback_data="c_restart"), IB("❌ Отмена", callback_data="c_cancel")],
        ]
    )
    await update.effective_message.reply_text("Вот как будет выглядеть карточка 👇", reply_markup=MAIN_KB)
    await update.effective_message.reply_photo(d["photos"][0], caption=draft_caption(d, user), parse_mode=H, reply_markup=kb)


def publish(d: dict, user: dict) -> dict:
    loc = {
        "id": f"u{user['id']}_{int(time.time())}",
        "emoji": "📍",
        "title": d["title"],
        "place": d.get("address") or "Ленинградская область",
        "lat": d.get("lat"),
        "lon": d.get("lon"),
        "xp": C.USER_LOCATION_XP,
        "intro": d["desc"],
        "hint": "Подсказка в описании автора. Смотри внимательно на фото!",
        "photos": d["photos"],
        "tasks": [{"type": "input", "q": d["question"], "answers": [d["answer"]]}],
        "author": {"id": user["id"], "name": user["name"], "username": user.get("username")},
    }
    store.data["locations"].append(loc)
    user["created"].append(loc["id"])
    return loc


async def submit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    d = ctx.user_data.get("draft")
    if not d or ctx.user_data.get("mode") != "c_preview":
        await q.answer("Черновик не найден", show_alert=True)
        return
    user = store.user(update.effective_user)
    await q.edit_message_reply_markup(None)

    if config.MODERATION == "manual" and config.ADMIN_IDS:
        pid = f"p{user['id']}_{int(time.time())}"
        store.data["pending"][pid] = {"draft": d, "user": user["id"]}
        store.save()
        for admin in config.ADMIN_IDS:
            try:
                await ctx.bot.send_photo(
                    admin, d["photos"][0], caption="🛡 Новая заявка\n\n" + draft_caption(d, user), parse_mode=H,
                    reply_markup=IKM([[IB("✅ Опубликовать", callback_data=f"mod_ok:{pid}"), IB("❌ Отклонить", callback_data=f"mod_no:{pid}")]]),
                )
            except Exception as ex:
                log.warning("admin %s unreachable: %s", admin, ex)
        reset_mode(ctx)
        await q.message.reply_text("🕓 Заявка отправлена кураторам. Мы напишем, когда след появится на карте!", reply_markup=MAIN_KB)
        return

    # mock automatic moderation with a little "live" animation
    ok, checks = game.moderate(d)
    status = await q.message.reply_text("🕓 <b>На модерации…</b>", parse_mode=H)
    shown = []
    for line in checks:
        await asyncio.sleep(0.8)
        shown.append(line)
        await status.edit_text("🔎 <b>Проверяем заявку…</b>\n" + "\n".join(shown), parse_mode=H)
    await asyncio.sleep(0.8)
    if not ok:
        ctx.user_data["mode"] = "c_preview"
        await status.edit_text("❌ <b>Заявка не прошла проверку</b>\n" + "\n".join(checks), parse_mode=H)
        await q.message.reply_text(
            "Исправь и попробуй снова.",
            reply_markup=IKM([[IB("✏️ Заполнить заново", callback_data="c_restart")]]),
        )
        return
    loc = publish(d, user)
    _, up = game.add_xp(user, C.XP_CREATE)
    new = ["creator"] if game.grant(user, "creator") else []
    store.save()
    reset_mode(ctx)
    await status.edit_text(
        "✅ <b>Опубликовано на общей карте!</b>\n" + "\n".join(checks) + f"\n\n+{C.XP_CREATE} XP за новый след",
        parse_mode=H,
    )
    await q.message.reply_text(
        f"Теперь «{e(loc['title'])}» видят все игроки.{author_line(loc)}\n"
        f"Когда кто-то пройдёт твой след, ты получишь +{C.XP_AUTHOR_ROYALTY} XP ✨",
        parse_mode=H,
        reply_markup=MAIN_KB,
    )
    await announce(update, user, new, up)


async def moderate_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ok: bool, pid: str) -> None:
    q = update.callback_query
    if update.effective_user.id not in config.ADMIN_IDS:
        await q.answer("Только для кураторов", show_alert=True)
        return
    item = store.data["pending"].pop(pid, None)
    if not item:
        await q.answer("Уже обработано")
        return
    user = store.get_user(item["user"])
    await q.edit_message_reply_markup(None)
    if ok and user:
        loc = publish(item["draft"], user)
        game.add_xp(user, C.XP_CREATE)
        game.grant(user, "creator")
        await ctx.bot.send_message(user["id"], f"✅ Твой след «{e(loc['title'])}» опубликован! +{C.XP_CREATE} XP\n✍️ <b>Ачивка: Созидатель</b>", parse_mode=H)
        await q.message.reply_text("Опубликовано ✅")
    elif user:
        await ctx.bot.send_message(user["id"], "❌ Куратор отклонил заявку. Попробуй добавить другое место или больше деталей.")
        await q.message.reply_text("Отклонено ❌")
    store.save()


# ---------- profile, top, certificate, invite ----------
async def profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = store.user(update.effective_user)
    lvl, name, nxt = game.level_of(user["xp"])
    left = f"ещё {nxt - user['xp']} XP до уровня {lvl + 1}" if nxt else "максимальный уровень"
    have = [game.badge(k) for k in C.ACHIEVEMENTS if k in user["achievements"]]
    locked = [f"🔒 {v[1]}" for k, v in C.ACHIEVEMENTS.items() if k not in user["achievements"]]
    text = (
        f"👤 <b>{e(user['name'])}</b>\n\n"
        f"⭐ Уровень {lvl} · <b>{name}</b>\n{game.progress_bar(user['xp'])} {user['xp']} XP\n<i>{left}</i>\n\n"
        f"🏆 Место в рейтинге: #{store.rank(user['id'])}\n"
        f"🔍 Квестов пройдено: {len(user['done'])}/{len(game.all_locations())}\n"
        f"👣 Следов оставлено: {len(user['created'])}\n🤝 Друзей приглашено: {user['invites']}\n\n"
        f"<b>Ачивки ({len(have)}/{len(C.ACHIEVEMENTS)})</b>\n" + "\n".join(have + locked)
    )
    await update.effective_message.reply_text(
        text, parse_mode=H, reply_markup=IKM([[IB("📜 Сертификат", callback_data="cert"), IB("🗺 Квесты", callback_data="list")]])
    )


async def top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    me = store.user(update.effective_user)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, u in enumerate(store.top(10)):
        mark = medals[i] if i < 3 else f"{i + 1}."
        name = e(u["name"]) + (" ← ты" if u["id"] == me["id"] else "")
        lines.append(f"{mark} {name} · {u['xp']} XP")
    await update.effective_message.reply_text(
        "🏆 <b>Рейтинг участников</b>\n\n" + "\n".join(lines) + f"\n\nТвоё место: #{store.rank(me['id'])}",
        parse_mode=H,
    )


async def cert(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = store.user(update.effective_user)
    msg = update.effective_message
    if user["xp"] < config.CERT_MIN_XP:
        need = config.CERT_MIN_XP - user["xp"]
        filled = round(user["xp"] / config.CERT_MIN_XP * 10)
        await msg.reply_text(
            f"📜 Сертификат откроется с {config.CERT_MIN_XP} XP.\n{'▰' * filled}{'▱' * (10 - filled)} осталось {need} XP\n\n"
            "Пройди пару квестов или оставь свой след 👣",
            reply_markup=IKM([[IB("🗺 К квестам", callback_data="list")]]),
        )
        return
    await ctx.bot.send_chat_action(msg.chat_id, "upload_document")
    number = user.get("cert_id") or store.next_cert_number()
    user["cert_id"] = number
    store.save()
    png, pdf, cert_id = await asyncio.to_thread(
        certificate.render, user, number, game.now_local().strftime("%d.%m.%Y")
    )
    await msg.reply_photo(
        png,
        caption=f"🎓 <b>Сертификат участника «След»</b>\n№ {cert_id}\n\n"
        "Его можно приложить для учёта внеучебной активности и бонусов к рейтингу (БРС / ВСР).",
        parse_mode=H,
    )
    await msg.reply_document(pdf, filename=f"{cert_id}.pdf")


async def invite(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    link = f"https://t.me/{ctx.bot.username}?start=ref_{uid}"
    await update.effective_message.reply_text(
        f"🤝 Зови друзей в квест! За каждого друга: <b>+{C.XP_INVITE} XP</b>\n\nТвоя ссылка:\n{link}",
        parse_mode=H,
        disable_web_page_preview=True,
    )


async def near(update: Update, ctx: ContextTypes.DEFAULT_TYPE, lat: float, lon: float) -> None:
    locs = [l for l in game.all_locations() if l.get("lat") is not None]
    locs.sort(key=lambda l: game.distance_m(lat, lon, l["lat"], l["lon"]))
    rows = [
        [IB(f"{l['emoji']} {l['title']} · {game.human_distance(game.distance_m(lat, lon, l['lat'], l['lon']))}", callback_data=f"loc:{l['id']}")]
        for l in locs[:5]
    ]
    await update.effective_message.reply_text("📍 <b>Ближайшие следы</b>", parse_mode=H, reply_markup=IKM(rows))
    await update.effective_message.reply_text("Выбирай!", reply_markup=MAIN_KB)


# ---------- routers ----------
MENU = {B_SEEK: seek, B_CREATE: create_start, B_PROFILE: profile, B_TOP: top, B_CERT: cert, B_INVITE: invite, B_CANCEL: cancel}


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data
    store.user(update.effective_user)
    if data == "list":
        await q.answer()
        await seek(update, ctx)
    elif data == "near":
        await q.answer()
        ctx.user_data["mode"] = "near"
        await q.message.reply_text("Отправь свою геолокацию 👇", reply_markup=GEO_KB)
    elif data.startswith("loc:"):
        await q.answer()
        await show_location(update, ctx, data[4:])
    elif data.startswith("go:"):
        await q.answer("Удачи! 🍀")
        await start_quest(update, ctx, data[3:])
    elif data.startswith("here:"):
        qs = ctx.user_data.get("quest")
        if ctx.user_data.get("mode") != "visit" or not qs or qs["loc"] != data[5:]:
            await q.answer("Сначала начни этот квест", show_alert=True)
            return
        await q.answer("🧪 Демо-режим")
        await visit_confirmed(update, ctx, "демо")
    elif data.startswith("ans:"):
        qs = ctx.user_data.get("quest")
        if ctx.user_data.get("mode") != "task" or not qs:
            await q.answer("Этот вопрос уже закрыт")
            return
        task = game.get_location(qs["loc"])["tasks"][qs["task"]]
        if task["type"] != "quiz":
            await q.answer()
            return
        correct = int(data[4:]) == task["correct"]
        await q.answer("✅" if correct else "❌")
        if correct:
            await q.edit_message_reply_markup(None)
        await task_result(update, ctx, correct)
    elif data == "hint":
        qs = ctx.user_data.get("quest")
        if ctx.user_data.get("mode") == "task" and qs:
            task = game.get_location(qs["loc"])["tasks"][qs["task"]]
            qs["attempts"] += 1  # a hint costs like a wrong attempt
            await q.answer(task.get("hint", "Подсказки нет")[:190], show_alert=True)
        else:
            await q.answer()
    elif data == "cert":
        await q.answer()
        await cert(update, ctx)
    elif data == "c_photos_done":
        await q.answer()
        if ctx.user_data.get("mode") == "c_photos" and ctx.user_data["draft"]["photos"]:
            await q.edit_message_reply_markup(None)
            await photos_done(update, ctx)
    elif data == "c_submit":
        await q.answer()
        await submit(update, ctx)
    elif data == "c_restart":
        await q.answer()
        await create_start(update, ctx)
    elif data == "c_cancel":
        await q.answer()
        await cancel(update, ctx)
    elif data.startswith("mod_ok:") or data.startswith("mod_no:"):
        await moderate_cb(update, ctx, data.startswith("mod_ok:"), data[7:])
    else:
        await q.answer()


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    store.user(update.effective_user)
    text = (msg.text or "").strip()

    if text in MENU:
        await MENU[text](update, ctx)
        return

    if await creator_step(update, ctx):
        return

    mode = ctx.user_data.get("mode")
    qs = ctx.user_data.get("quest")

    if mode == "near" and msg.location:
        ctx.user_data.pop("mode", None)
        await near(update, ctx, msg.location.latitude, msg.location.longitude)
        return

    if mode == "visit" and qs:
        loc = game.get_location(qs["loc"])
        if msg.location:
            if loc.get("lat") is None:
                await visit_confirmed(update, ctx, "геолокация")
                return
            dist = game.distance_m(msg.location.latitude, msg.location.longitude, loc["lat"], loc["lon"])
            if dist <= config.VISIT_RADIUS_M:
                await visit_confirmed(update, ctx, f"ты в {game.human_distance(dist)} от точки")
            else:
                extra = "\n🧪 Или нажми «Я на месте (демо)» выше." if config.DEMO_MODE else ""
                await msg.reply_text(
                    f"📏 До точки ещё <b>{game.human_distance(dist)}</b>. Подойди ближе (радиус {config.VISIT_RADIUS_M} м) "
                    f"или отправь селфи на месте.{extra}",
                    parse_mode=H,
                )
            return
        if msg.photo:
            await visit_confirmed(update, ctx, "фотоотчёт")
            return
        await msg.reply_text("Подтверди визит: геолокация или селфи 📸", reply_markup=GEO_KB)
        return

    if mode == "task" and qs:
        task = game.get_location(qs["loc"])["tasks"][qs["task"]]
        t = task["type"]
        if t == "input" and text:
            await task_result(update, ctx, game.check_input(task, text))
        elif t == "quiz":
            await msg.reply_text("Выбери вариант кнопкой выше 👆")
        elif t == "voice" and (msg.voice or msg.audio or msg.video_note):
            await msg.reply_text("🎧 Слушаем… Отличное произношение!")
            await task_result(update, ctx, True)
        elif t == "voice" and len(text) >= task.get("min_chars", 60):
            await task_result(update, ctx, True)
        elif t == "voice":
            await msg.reply_text("Лучше голосом 🎙 (или текстом от 60 символов).")
        elif t == "photo" and msg.photo:
            await msg.reply_text("📸 Кадр принят!")
            await task_result(update, ctx, True)
        else:
            await msg.reply_text("Жду ответ на задание 🙂")
        return

    # idle
    if msg.location:
        await near(update, ctx, msg.location.latitude, msg.location.longitude)
    elif msg.photo:
        await msg.reply_text("Красивое место! Хочешь добавить его на карту? Жми «👣 Оставить след».", reply_markup=MAIN_KB)
    else:
        await msg.reply_text("Выбери действие в меню 👇", reply_markup=MAIN_KB)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error", exc_info=ctx.error)


def build_app() -> Application:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Put it into .env (see .env.example).")
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("demo", demo_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("cert", cert))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


async def _set_commands(app: Application) -> None:
    from telegram import BotCommand

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Главное меню"),
            BotCommand("profile", "Мой профиль"),
            BotCommand("top", "Рейтинг"),
            BotCommand("cert", "Сертификат"),
            BotCommand("help", "Помощь"),
        ]
    )


if __name__ == "__main__":
    application = build_app()
    application.post_init = _set_commands
    log.info("«След» bot started. Demo mode: %s, moderation: %s", config.DEMO_MODE, config.MODERATION)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
