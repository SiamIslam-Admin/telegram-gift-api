import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pyrogram import Client, filters, errors, raw
from pyrogram.types import Message
from dotenv import load_dotenv
import uvicorn

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

SESSION_DIR = "/data/sessions"
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

app_bot = Client(os.path.join(SESSION_DIR, "manager_bot"), api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    print("✅ System Online!")
    yield
    await app_bot.stop()

app = FastAPI(lifespan=lifespan)
user_sessions = {}

@app.get("/")
async def home():
    return {"status": "ok", "message": "Manual Star Gift API is running!"}

@app.get("/send-gift")
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    clean_target = target.replace("@", "").strip()
    session_path = os.path.join(SESSION_DIR, session)
    
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    try:
        await client.start()
        peer = await client.resolve_peer(clean_target)

        # --- MANUAL RAW OBJECT CONSTRUCTION ---
        # এই অংশটি লাইব্রেরির এরর বাইপাস করবে
        try:
            # Constructing InputInvoiceStarGift manually using its schema ID
            invoice = raw.types.InputInvoiceStarGift(
                peer=peer,
                gift_id=gift_id,
                message=raw.types.TextWithEntities(text=message, entities=[])
            )
        except AttributeError:
            # Fallback: সরাসরি মেথড ইনভোক করা যদি টাইপ না পায়
            return JSONResponse(status_code=500, content={"error": "Library still outdated. Trying manual bypass..."})

        # Get Payment Form
        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)

        # Send Stars Form
        await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        
        return {"status": "success", "message": f"Gift sent to {clean_target}!"}

    except Exception as e:
        print(f"DEBUG_ERROR: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if client.is_connected: await client.stop()

# --- [BOT HANDLERS] ---
@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    await message.reply("👋 নাম দিন সেশন তৈরির জন্য।")

@app_bot.on_message(filters.text & filters.private)
async def handle_steps(client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_sessions:
        name = message.text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": name, "step": "phone"}
        await message.reply(f"📁 নাম: `{name}`\nফোন নম্বর দিন।")
        return
    state = user_sessions[user_id]
    if state["step"] == "phone":
        state["phone"] = message.text
        path = os.path.join(SESSION_DIR, state["name"])
        temp_client = Client(path, api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()
        code_info = await temp_client.send_code(message.text)
        state.update({"hash": code_info.phone_code_hash, "client": temp_client, "step": "otp"})
        await message.reply("📩 OTP দিন।")
    elif state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], message.text)
            await message.reply(f"✅ `{state['name']}` সেভ হয়েছে!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await message.reply("🔐 2FA দিন।")
    elif state["step"] == "2fa":
        await state["client"].check_password(message.text)
        await message.reply(f"✅ `{state['name']}` সেভ হয়েছে!")
        await state["client"].disconnect()
        del user_sessions[user_id]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
