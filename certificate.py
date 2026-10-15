"""Certificate generator (PNG + PDF) with Pillow."""
import hashlib
import math
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import config
import content as C
import game

W, H = 2480, 1754  # A4 landscape @ 300 dpi
CYAN = (14, 177, 210)
CYAN_D = (10, 143, 170)
SOFT = (209, 242, 248)
MIST = (238, 250, 252)
INK = (22, 23, 27)
GREY = (112, 112, 120)

FONTS = config.ASSETS / "fonts"


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)


def fit(draw, text, weight, size, max_w):
    """Shrink font until text fits max_w."""
    while size > 40:
        f = font(weight, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return font(weight, size)


def verify_code(user_id: int, number: int) -> str:
    return hashlib.sha256(f"sled:{user_id}:{number}".encode()).hexdigest()[:8].upper()


def dotted_path(draw, pts, color, r=7, step=46):
    """Draw the 'trail' motif: dots along a polyline."""
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.dist((x1, y1), (x2, y2))
        t = acc
        while t < seg:
            x, y = x1 + (x2 - x1) * t / seg, y1 + (y2 - y1) * t / seg
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
            t += step
        acc = t - seg


def render(user: dict, number: int, issued: str) -> tuple[bytes, bytes, str]:
    """Returns (png bytes, pdf bytes, certificate id)."""
    cert_id = f"SLED-2027-{number:05d}"
    code = verify_code(user["id"], number)
    lvl, lvl_name, _ = game.level_of(user["xp"])

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # frame
    d.rounded_rectangle((60, 60, W - 60, H - 60), radius=60, outline=SOFT, width=6)
    d.rounded_rectangle((100, 100, W - 100, H - 100), radius=44, outline=MIST, width=3)

    # logo
    logo = Image.open(config.ASSETS / "logo.png").convert("RGBA")
    lw = 560
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    img.paste(logo, (220, 220), logo)

    # header
    d.text((220, 470), "СЕРТИФИКАТ", font=font("SemiBold", 52), fill=CYAN_D, spacing=0)
    d.text((220, 545), "участника социально-культурного проекта «След»", font=font("Regular", 56), fill=GREY)

    # name
    name = user["name"] or (("@" + user["username"]) if user.get("username") else "Участник")
    d.text((220, 670), name, font=fit(d, name, "ExtraBold", 150, W - 900), fill=INK)
    dotted_path(d, [(230, 880), (700, 905), (1150, 870), (1600, 895)], CYAN)

    # stats
    stats = [
        (str(user["xp"]), "очков XP"),
        (f"{lvl}", f"уровень · {lvl_name}"),
        (str(len(user["done"])), "квестов пройдено"),
        (str(len(user["created"])), "следов оставлено"),
    ]
    x = 220
    for big, small in stats:
        d.rounded_rectangle((x, 990, x + 420, 1230), radius=36, fill=MIST)
        d.text((x + 44, 1010), big, font=font("ExtraBold", 110), fill=CYAN)
        d.text((x + 46, 1160), small, font=fit(d, small, "SemiBold", 40, 340), fill=INK)
        x += 460

    # achievements (names only, emoji fonts are not portable)
    ach = [C.ACHIEVEMENTS[k][1] for k in user["achievements"] if k in C.ACHIEVEMENTS]
    if ach:
        d.text((220, 1290), "Достижения: " + " · ".join(ach), font=fit(d, "Достижения: " + " · ".join(ach), "Regular", 44, W - 900), fill=GREY)

    # footer
    d.text((220, 1440), f"№ {cert_id}   ·   выдан {issued}   ·   код проверки {code}", font=font("Regular", 40), fill=GREY)
    d.text((220, 1500), "Для учёта внеучебной активности и бонусов БРС / ВСР по гуманитарным дисциплинам",
           font=font("Regular", 36), fill=GREY)
    d.text((220, 1560), "Демонстрационная версия", font=font("SemiBold", 32), fill=(170, 176, 182))

    # seal
    cx, cy, r = W - 420, 520, 210
    d.ellipse((cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26), fill=SOFT)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CYAN)
    f = font("ExtraBold", 220)
    d.text((cx, cy - 10), "С", font=f, fill="white", anchor="mm")
    d.text((cx, cy + r + 90), "ОСТАВЬ СВОЙ СЛЕД", font=font("SemiBold", 36), fill=CYAN_D, anchor="mm")

    png = BytesIO()
    img.save(png, "PNG", optimize=True)
    pdf = BytesIO()
    img.save(pdf, "PDF", resolution=300)
    return png.getvalue(), pdf.getvalue(), cert_id
