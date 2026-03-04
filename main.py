import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pyrogram import Client, filters, errors, raw
from pyrogram.types import Message
from dotenv import load_dotenv
import uvicorn

# Load Environment Variables
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Persistent Volume Path (Must be mounted in Railway)
SESSION_DIR = "/data/sessions"
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

# Main Bot Client for session generation
app_bot = Client(
    os.path.join(SESSION_DIR, "manager_bot"), 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    print("✅ System Online and Bot Started!")
    yield
    await app_bot.stop()

app = FastAPI(lifespan=lifespan)
user_sessions = {}

# --- [API ENDPOINTS] ---

@app.get("/")
async def home():
    import pyrogram
    return {
        "status": "online", 
        "pyrogram_version": pyrogram.__version__,
        "message": "Visit /send-gift to send star gifts."
    }

@app.api_route("/send-gift", methods=["GET", "POST"])
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    clean_target = target.replace("@", "").strip()
    session_path = os.path.join(SESSION_DIR, session)
    
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    try:
        await client.start()
        peer = await client.resolve_peer(clean_target)

        # Force checking for Star Gift support
        if not hasattr(raw.types, "InputInvoiceStarGift"):
            return JSONResponse(status_code=500, content={
                "error": "Pyrogram Version Error",
                "details": "Star Gifts not supported in current library version. Please update requirements.txt"
            })

        invoice = raw.types.InputInvoiceStarGift(
            peer=peer, 
            gift_id=gift_id,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )

        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
        
        await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        return {"status": "success", "message": f"Gift sent to {clean_target}!"}

    except Exception as e:
        print(f"DEBUG_ERROR: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if client.is_connected: 
            await client.stop()

# --- [BOT HANDLERS] ---

@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    await message.reply("👋 **Session Manager**\nSend a name (e.g., `user01`) to start creating a session.")

@app_bot.on_message(filters.text & filters.private)
async def handle_steps(client, message: Message):
    user_id = message.from_user.id
    text = message.text

    if user_id not in user_sessions:
        name = text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": name, "step": "phone"}
        await message.reply(f"📁 Name: `{name}`\nNow send your **Phone Number** (+880...).")
        return

    state = user_sessions[user_id]
    
    if state["step"] == "phone":
        state["phone"] = text
        path = os.path.join(SESSION_DIR, state["name"])
        temp_client = Client(path, api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()
        try:
            code_info = await temp_client.send_code(text)
            state.update({"hash": code_info.phone_code_hash, "client": temp_client, "step": "otp"})
            await message.reply("📩 **OTP Sent!** Enter it here:")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")
            await temp_client.disconnect()
            del user_sessions[user_id]

    elif state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], text)
            await message.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await message.reply("🔐 **2FA Required!** Enter password:")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")

    elif state["step"] == "2fa":
        try:
            await state["client"].check_password(text)
            await message.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except Exception as e:
            await message.reply(f"❌ Wrong Password: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
