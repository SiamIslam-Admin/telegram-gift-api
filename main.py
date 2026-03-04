import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from pyrogram import Client, filters, errors, raw
from pyrogram.types import Message

import uvicorn

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

SESSION_DIR = os.getenv("SESSION_DIR", "/data/sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

def make_session_path(name: str) -> str:
    return os.path.join(SESSION_DIR, name)

app_bot = Client(
    make_session_path("manager_bot"),
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_sessions = {}

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
    return {"status": "online", "pyrogram": pyrogram.__version__}

@app.api_route("/send-gift", methods=["GET", "POST"])
async def send_gift_api(
    gift_id: str = Query(...),
    target: str = Query(...),
    session: str = Query(...),
    message: str = Query("Enjoy!")
):
    clean_target = target.replace("@", "").strip()
    session_path = make_session_path(session)

    if not os.path.exists(session_path + ".session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)

    try:
        await client.start()
        peer = await client.resolve_peer(clean_target)

        try:
            gift_int = int(gift_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "gift_id must be numeric"})

        invoice = raw.types.InputInvoiceStarGift(
            peer=peer,
            gift_id=gift_int,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )

        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)

        if not form_id:
            return JSONResponse(status_code=500, content={"error": "Payment form_id missing"})

        await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        return {"status": "success", "message": f"Gift sent to {clean_target}!"}

    except Exception as e:
        print("❌ /send-gift error:", str(e))
        print(traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})

    finally:
        if client.is_connected:
            await client.stop()

# --- BOT HANDLERS ---

@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(c, m: Message):
    await m.reply("👋 Send a name to create a session.")

@app_bot.on_message(filters.text & filters.private)
async def handle_steps(c, m: Message):
    user_id = m.from_user.id

    if user_id not in user_sessions:
        name = m.text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": name, "step": "phone"}
        await m.reply(f"📁 Name: `{name}`\nSend Phone Number:")
        return

    state = user_sessions[user_id]

    if state["step"] == "phone":
        state["phone"] = m.text.strip()
        path = make_session_path(state["name"])

        temp_client = Client(path, api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()

        code_info = await temp_client.send_code(state["phone"])
        state.update({
            "hash": code_info.phone_code_hash,
            "client": temp_client,
            "step": "otp"
        })

        await m.reply("📩 OTP Sent! Now send OTP:")
        return

    if state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], m.text.strip())
            await m.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
            return
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await m.reply("🔐 Enter 2FA Password:")
            return
        except Exception as e:
            print("❌ OTP error:", str(e))
            print(traceback.format_exc())
            await m.reply(f"❌ OTP failed: {e}")
            return

    if state["step"] == "2fa":
        try:
            await state["client"].check_password(m.text)
            await m.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
            return
        except Exception as e:
            print("❌ 2FA error:", str(e))
            print(traceback.format_exc())
            await m.reply(f"❌ 2FA failed: {e}")
            return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
