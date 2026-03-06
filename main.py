import os
import traceback
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from pyrogram import Client, filters, errors, raw
from pyrogram.types import Message
import os
import secrets
import string
import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from pyrogram import Client, filters, errors, raw
from pyrogram.types import (
    Message,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# -------------------------
# CONFIG & ENV
# -------------------------
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_DIR = os.getenv("SESSION_DIR", "./sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

# Temporary storage for login states
user_sessions = {}

# Prevent concurrent usage of the same session file
session_locks: dict[str, asyncio.Lock] = {}


def get_session_lock(session_name: str) -> asyncio.Lock:
    if session_name not in session_locks:
        session_locks[session_name] = asyncio.Lock()
    return session_locks[session_name]


# -------------------------
# UTILS
# -------------------------
def generate_secure_suffix(length=6):
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def get_all_sessions():
    return [
        f.replace(".session", "")
        for f in os.listdir(SESSION_DIR)
        if f.endswith(".session") and "manager_bot" not in f
    ]


# -------------------------
# BOT KEYBOARDS
# -------------------------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["👤 Create via Account", "🤖 Create via Bot Token"],
        ["📊 Get Session Details"]
    ],
    resize_keyboard=True
)

# -------------------------
# PYROGRAM BOT INSTANCE
# -------------------------
app_bot = Client(
    "manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=SESSION_DIR
)

# -------------------------
# FASTAPI LIFESPAN
# -------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    print("🚀 Bot and API are online!")
    yield
    await app_bot.stop()

app = FastAPI(lifespan=lifespan)

# -------------------------
# BOT HANDLERS
# -------------------------
@app_bot.on_message(filters.command("start") & filters.private)
async def start_handler(c, m: Message):
    await m.reply(
        "💎 **Advanced Session Manager**\n\n"
        "Choose an option below to create or manage your Telegram sessions securely.",
        reply_markup=MAIN_MENU
    )


@app_bot.on_message(filters.text & filters.private)
async def menu_logic(c, m: Message):
    user_id = m.from_user.id
    text = m.text

    if text == "👤 Create via Account":
        user_sessions[user_id] = {"step": "naming", "type": "user"}
        await m.reply("🏷️ Enter a **Nickname** for this account:")
        return

    if text == "🤖 Create via Bot Token":
        user_sessions[user_id] = {"step": "naming", "type": "bot"}
        await m.reply("🏷️ Enter a **Nickname** for this bot:")
        return

    if text == "📊 Get Session Details":
        sessions = get_all_sessions()
        if not sessions:
            await m.reply("📭 No sessions found in storage.")
            return

        await m.reply(f"📂 **Found {len(sessions)} sessions:**")
        for s in sessions:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 View Details & Stars", callback_data=f"info_{s}")],
                [InlineKeyboardButton("🗑️ Delete Session", callback_data=f"del_{s}")]
            ])
            await m.reply(f"📦 ID: `{s}`", reply_markup=kb)
        return

    if user_id not in user_sessions:
        return

    state = user_sessions[user_id]

    if state["step"] == "naming":
        safe_name = "".join(x for x in text if x.isalnum())[:10]
        random_id = generate_secure_suffix()
        final_filename = f"{safe_name}_{random_id}"
        state["filename"] = final_filename

        if state["type"] == "user":
            state["step"] = "phone"
            await m.reply(
                f"📄 File: `{final_filename}`\n"
                f"📞 Send **Phone Number** (with country code):"
            )
        else:
            state["step"] = "bot_token"
            await m.reply(
                f"📄 File: `{final_filename}`\n"
                f"🤖 Send **Bot Token**:"
            )
        return

    if state["step"] == "bot_token":
        client = Client(
            state["filename"],
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=SESSION_DIR,
            no_updates=True
        )
        try:
            await client.connect()
            await client.sign_in_bot(text)
            await m.reply(f"✅ Bot session `{state['filename']}` saved!")
        except Exception as e:
            await m.reply(f"❌ Failed: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
            user_sessions.pop(user_id, None)
        return

    if state["step"] == "phone":
        client = Client(
            state["filename"],
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=SESSION_DIR,
            no_updates=True
        )
        try:
            await client.connect()
            code = await client.send_code(text)
            state.update({
                "client": client,
                "phone": text,
                "hash": code.phone_code_hash,
                "step": "otp"
            })
            await m.reply("📩 OTP Sent! Enter code:")
        except Exception as e:
            await m.reply(f"❌ Error: {e}")
            if client.is_connected:
                await client.disconnect()
            user_sessions.pop(user_id, None)
        return

    if state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], text)
            await m.reply(f"✅ Session `{state['filename']}` active!")
            if state["client"].is_connected:
                await state["client"].disconnect()
            user_sessions.pop(user_id, None)
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await m.reply("🔐 2FA Password required:")
        except Exception as e:
            await m.reply(f"❌ Failed: {e}")
        return

    if state["step"] == "2fa":
        try:
            await state["client"].check_password(text)
            await m.reply(f"✅ Session `{state['filename']}` (2FA) active!")
            if state["client"].is_connected:
                await state["client"].disconnect()
            user_sessions.pop(user_id, None)
        except Exception as e:
            await m.reply(f"❌ 2FA Error: {e}")


# -------------------------
# CALLBACKS
# -------------------------
@app_bot.on_callback_query()
async def handle_callbacks(c, q: CallbackQuery):
    data = q.data

    if data.startswith("info_"):
        session_id = data.replace("info_", "")
        await q.answer("Fetching data...")

        client = Client(
            session_id,
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=SESSION_DIR,
            no_updates=True
        )

        try:
            await client.connect()

            if not await client.get_me():
                await q.edit_message_text("❌ Session is not authorized.")
                return

            me = await client.get_me()
            stars = await client.invoke(
                raw.functions.payments.GetStarsStatus(
                    peer=await client.resolve_peer("me")
                )
            )
            balance = getattr(stars, "balance", 0)

            status_text = (
                f"📝 **Details for:** `{session_id}`\n\n"
                f"👤 **User:** {me.first_name}\n"
                f"🆔 **ID:** `{me.id}`\n"
                f"⭐ **Stars Available:** `{balance}`\n"
                f"🤖 **Is Bot:** {me.is_bot}"
            )
            await q.edit_message_text(status_text, reply_markup=q.message.reply_markup)

        except Exception as e:
            await q.edit_message_text(f"❌ Session Error: {e}\nSession might be expired.")
        finally:
            if client.is_connected:
                await client.disconnect()

    elif data.startswith("del_"):
        session_id = data.replace("del_", "")
        path = os.path.join(SESSION_DIR, f"{session_id}.session")
        if os.path.exists(path):
            os.remove(path)
            await q.edit_message_text(f"🗑️ Session `{session_id}` deleted permanently.")
        else:
            await q.answer("File not found.")


# -------------------------
# API ENDPOINT (GIFT SENDER)
# -------------------------
@app.get("/send-gift")
async def send_gift_api(
    target: str = Query(..., description="Username or peer"),
    session: str = Query(..., description="Session name without .session"),
    gift_id: int = Query(..., description="Telegram star gift id"),
    message: str = Query("Gift!")
):
    session_path = os.path.join(SESSION_DIR, f"{session}.session")
    if not os.path.exists(session_path):
        return JSONResponse(
            status_code=404,
            content={"error": "Session file missing."}
        )

    lock = get_session_lock(session)

    async with lock:
        client = Client(
            session,
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=SESSION_DIR,
            no_updates=True
        )

        try:
            # connect() instead of start() -> no update handler issues
            await client.connect()

            me = await client.get_me()
            if not me:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Session is not authorized."}
                )

            clean_target = target.lstrip("@")
            peer = await client.resolve_peer(clean_target)

            invoice = raw.types.InputInvoiceStarGift(
                peer=peer,
                gift_id=gift_id,
                message=raw.types.TextWithEntities(
                    text=message,
                    entities=[]
                )
            )

            form = await client.invoke(
                raw.functions.payments.GetPaymentForm(invoice=invoice)
            )

            form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
            if not form_id:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Could not fetch payment form id."}
                )

            result = await client.invoke(
                raw.functions.payments.SendStarsForm(
                    form_id=form_id,
                    invoice=invoice
                )
            )

            return {
                "status": "success",
                "session": session,
                "target": clean_target,
                "gift_id": gift_id,
                "result": str(result)
            }

        except errors.UsernameNotOccupied:
            return JSONResponse(
                status_code=404,
                content={"error": f"Target username not found: {target}"}
            )
        except errors.PeerIdInvalid:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid target peer: {target}"}
            )
        except errors.FloodWait as e:
            return JSONResponse(
                status_code=429,
                content={"error": f"Flood wait: retry after {e.value} seconds"}
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )
        finally:
            if client.is_connected:
                await client.disconnect()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# -------------------------
# ENV
# -------------------------
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TELEGRAM_2FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD", "")  # optional

# -------------------------
# SESSION STORAGE
# -------------------------
SESSION_DIR = os.getenv("SESSION_DIR", "/data/sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

def make_session_path(name: str) -> str:
    return os.path.join(SESSION_DIR, name)

# -------------------------
# BOT CLIENT (manager bot)
# -------------------------
app_bot = Client(
    make_session_path("manager_bot"),
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_sessions = {}

async def start_with_optional_2fa(app: Client):
    try:
        await app.start()
    except errors.SessionPasswordNeeded:
        if TELEGRAM_2FA_PASSWORD:
            app.password = TELEGRAM_2FA_PASSWORD
            await app.start()
        else:
            raise

async def pick_gift_id(app: Client, requested: int | None) -> int:
    gifts_obj = await app.invoke(raw.functions.payments.GetStarGifts(hash=0))
    gifts = getattr(gifts_obj, "gifts", [])
    if not gifts:
        raise RuntimeError("No available gifts found in Telegram catalog.")

    if requested is not None:
        for g in gifts:
            if getattr(g, "id", None) == requested:
                return requested

    return gifts[0].id

@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    print("✅ Telegram Bot Started!")
    yield
    await app_bot.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def home():
    import pyrogram
    return {
        "status": "online",
        "pyrogram_version": pyrogram.__version__,
        "session_dir": SESSION_DIR
    }

@app.api_route("/send-gift", methods=["GET", "POST"])
async def send_gift_api(
    target: str = Query(...),
    session: str = Query(...),
    message: str = Query("Enjoy!"),
    gift_id: str | None = Query(None),
    hide_name: bool = Query(False),
    include_upgrade: bool = Query(False),
):
    clean_target = target.replace("@", "").strip()
    session_path = make_session_path(session)

    if not os.path.exists(session_path + ".session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)

    try:
        await start_with_optional_2fa(client)
        peer = await client.resolve_peer(clean_target)

        requested = None
        if gift_id:
            try:
                requested = int(gift_id)
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "gift_id must be numeric if provided"})

        valid_gift_id = await pick_gift_id(client, requested)

        invoice = raw.types.InputInvoiceStarGift(
            peer=peer,
            gift_id=valid_gift_id,
            hide_name=hide_name,
            include_upgrade=include_upgrade,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )

        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
        if not form_id:
            raise RuntimeError("Could not retrieve form_id from Telegram.")

        result = await client.invoke(
            raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice)
        )

        return {
            "status": "success",
            "target": clean_target,
            "session": session,
            "gift_id_used": valid_gift_id,
            "result": str(result)
        }

    except errors.SessionPasswordNeeded:
        return JSONResponse(status_code=401, content={"error": "2FA required. Set TELEGRAM_2FA_PASSWORD."})
    except errors.RPCError as e:
        return JSONResponse(status_code=400, content={"error": f"Telegram RPCError: {e}"})
    except Exception as e:
        print("❌ /send-gift error:", str(e))
        print(traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if client.is_connected:
            await client.stop()

# -------------------------
# BOT: session create
# -------------------------
@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(c, m: Message):
    await m.reply("👋 Send a name to create a session (example: tgdev).")

@app_bot.on_message(filters.text & filters.private)
async def handle_steps(c, m: Message):
    user_id = m.from_user.id

    if user_id not in user_sessions:
        name = m.text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": name, "step": "phone"}
        await m.reply(f"📁 Name: `{name}`\nSend Phone Number (with country code):")
        return

    state = user_sessions[user_id]

    if state["step"] == "phone":
        state["phone"] = m.text.strip()
        path = make_session_path(state["name"])

        temp_client = Client(path, api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()

        code = await temp_client.send_code(state["phone"])
        state.update({"hash": code.phone_code_hash, "client": temp_client, "step": "otp"})
        await m.reply("📩 OTP Sent! Now send OTP:")
        return

    if state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], m.text.strip())
            await m.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await m.reply("🔐 Enter 2FA Password:")
        except Exception as e:
            await m.reply(f"❌ OTP failed: {e}")

    elif state["step"] == "2fa":
        try:
            await state["client"].check_password(m.text)
            await m.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except Exception as e:
            await m.reply(f"❌ 2FA failed: {e}")

