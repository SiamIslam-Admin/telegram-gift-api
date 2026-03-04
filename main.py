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

# Persistent Volume Path
SESSION_DIR = "/data/sessions"
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

# Main Bot Client
app_bot = Client(
    os.path.join(SESSION_DIR, "manager_bot"), 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

# Startup/Shutdown Handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    print("✅ Telegram Bot & Session Manager Started!")
    yield
    await app_bot.stop()
    print("🛑 Bot Stopped!")

app = FastAPI(lifespan=lifespan)
user_sessions = {}

# --- [API ROUTES] ---

@app.get("/")
async def home():
    return {"status": "ok", "message": "Star Gift API is online!"}

@app.get("/list-sessions")
async def list_sessions():
    files = [f.replace(".session", "") for f in os.listdir(SESSION_DIR) if f.endswith(".session")]
    return {"total": len(files), "sessions": files}

@app.get("/send-gift")
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    # Auto-clean target (remove @ if present)
    clean_target = target.replace("@", "").strip()
    
    session_path = os.path.join(SESSION_DIR, session)
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    try:
        await client.start()
        
        # 1. Resolve Peer
        try:
            peer = await client.resolve_peer(clean_target)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": f"User not found: {str(e)}"})

        # 2. Build Invoice
        invoice = raw.types.InputInvoiceStarGift(
            peer=peer, 
            gift_id=gift_id,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )

        # 3. Request Payment Form and Send
        try:
            form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
            form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
            
            await client.invoke(raw.functions.payments.SendStarsForm(
                form_id=form_id, 
                invoice=invoice
            ))
            return {"status": "success", "message": f"Gift sent to {clean_target}!"}
            
        except errors.BalanceTooLow:
            return JSONResponse(status_code=402, content={"error": "Insufficient Telegram Stars balance in this account."})
        except Exception as e:
            print(f"DEBUG_ERROR: {str(e)}") # Visible in Railway Logs
            return JSONResponse(status_code=500, content={"error": "Telegram rejection", "details": str(e)})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Internal Client Error", "details": str(e)})
    finally:
        if client.is_connected: 
            await client.stop()

# --- [BOT HANDLERS] ---

@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    await message.reply("👋 **Session Generator**\nSend a unique name (e.g., `acc_01`) to start.")

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
            await message.reply("🔐 **2FA!** Enter password:")
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
    await app_bot.stop()
    print("🛑 Bot Stopped!")

app = FastAPI(lifespan=lifespan)
user_sessions = {}

# --- [ROUTES] ---

@app.get("/")
async def home():
    return {"status": "ok", "message": "Telegram Gift API & Bot is running!"}

@app.get("/list-sessions")
async def list_sessions():
    files = [f.replace(".session", "") for f in os.listdir(SESSION_DIR) if f.endswith(".session")]
    return {"total": len(files), "sessions": files}

@app.get("/send-gift")
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    session_path = os.path.join(SESSION_DIR, session)
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    try:
        await client.start()
        peer = await client.resolve_peer(target)
        
        # Using raw.types with a check for Star Gift support
        try:
            invoice = raw.types.InputInvoiceStarGift(
                peer=peer, 
                gift_id=gift_id,
                message=raw.types.TextWithEntities(text=message, entities=[])
            )
        except AttributeError:
            return JSONResponse(status_code=500, content={"error": "Pyrogram version is too old. Please update requirements.txt to git+https."})

        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
        
        await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        return {"status": "success", "message": f"Gift sent to {target} successfully!"}
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "details": str(e)})
    finally:
        if client.is_connected: 
            await client.stop()

# --- [BOT HANDLERS] ---

@app_bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    await message.reply("👋 **Welcome!**\nSend a unique name (e.g., `user_01`) to start creating a session.")

@app_bot.on_message(filters.text & filters.private)
async def handle_steps(client, message: Message):
    user_id = message.from_user.id
    text = message.text

    if user_id not in user_sessions:
        name = text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": name, "step": "phone"}
        await message.reply(f"📁 Session Name: `{name}`\nNow send your **Phone Number** (e.g., +88017...).")
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
            await message.reply("📩 **OTP Sent!** Enter the code here:")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")
            await temp_client.disconnect()
            del user_sessions[user_id]

    elif state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], text)
            await message.reply(f"✅ Session `{state['name']}` saved permanently!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await message.reply("🔐 **2FA Required!** Enter your cloud password:")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")

    elif state["step"] == "2fa":
        try:
            await state["client"].check_password(text)
            await message.reply(f"✅ Session `{state['name']}` verified and saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except Exception as e:
            await message.reply(f"❌ Wrong Password: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
    return {"status": "ok", "message": "Server is running perfectly!"}

# --- [বট সেকশন] ---
@app_bot.on_message(filters.command("start") & filters.private)
async def start(client, message: Message):
    await message.reply("👋 একটি নাম দিন সেশন তৈরির জন্য।")

@app_bot.on_message(filters.text & filters.private)
async def handle_auth(client, message: Message):
    user_id = message.from_user.id
    text = message.text

    if user_id not in user_sessions:
        session_name = text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": session_name, "step": "phone"}
        await message.reply(f"📁 সেশন নাম: `{session_name}`\nফোন নম্বর দিন (যেমন: +88017...)।")
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
            await message.reply("📩 OTP দিন।")
        except Exception as e:
            await message.reply(f"❌ এরর: {e}")
            await temp_client.disconnect()
            del user_sessions[user_id]

    elif state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], text)
            await message.reply(f"✅ সেশন `{state['name']}` সফলভাবে সেভ হয়েছে!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await message.reply("🔐 2FA পাসওয়ার্ড দিন।")
        except Exception as e:
            await message.reply(f"❌ এরর: {e}")

    elif state["step"] == "2fa":
        try:
            await state["client"].check_password(text)
            await message.reply(f"✅ সেশন `{state['name']}` তৈরি হয়েছে!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except Exception as e:
            await message.reply(f"❌ পাসওয়ার্ড ভুল: {e}")

# --- [API সেকশন] ---
@app.get("/send-gift")
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    session_path = os.path.join(SESSION_DIR, session)
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session {session} not found!"})

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    try:
        await client.start()
        peer = await client.resolve_peer(target)
        invoice = raw.types.InputInvoiceStarGift(
            peer=peer, gift_id=gift_id,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )
        form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
        form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
        await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        return {"status": "success", "message": f"Gift sent to {target}"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "details": str(e)})
    finally:
        if client.is_connected: await client.stop()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


