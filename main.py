import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telethon import TelegramClient, events, functions, types, errors
from dotenv import load_dotenv
import uvicorn

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

SESSION_DIR = "/data/sessions"
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

app = FastAPI()

# ম্যানেজার বট ক্লায়েন্ট (টেলিথন)
bot = TelegramClient(os.path.join(SESSION_DIR, "manager_bot"), API_ID, API_HASH).start(bot_token=BOT_TOKEN)

user_states = {}

@app.get("/")
async def home():
    return {"status": "online", "engine": "Telethon", "message": "Star Gift API is ready!"}

# --- [API: গিফট পাঠানো] ---
@app.get("/send-gift")
async def send_gift(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    session_path = os.path.join(SESSION_DIR, session)
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": f"Session '{session}' not found!"})

    # ক্লায়েন্ট চালু করা
    client = TelegramClient(session_path, API_ID, API_HASH)
    try:
        await client.connect()
        # গিফট পাঠানোর রিকোয়েস্ট (InputInvoiceStarGift)
        # টেলিথনে আমরা সরাসরি ইনভোক ব্যবহার করি
        result = await client(functions.payments.GetPaymentFormRequest(
            invoice=types.InputInvoiceStarGift(
                peer=target,
                gift_id=gift_id,
                message=types.TextWithEntities(text=message, entities=[])
            )
        ))
        
        form_id = result.form_id
        await client(functions.payments.SendStarsFormRequest(
            form_id=form_id,
            invoice=types.InputInvoiceStarGift(
                peer=target,
                gift_id=gift_id,
                message=types.TextWithEntities(text=message, entities=[])
            )
        ))
        return {"status": "success", "message": f"Gift sent to {target}!"}
    except errors.BalanceTooLowError:
        return JSONResponse(status_code=402, content={"error": "Insufficient Stars!"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        await client.disconnect()

# --- [BOT: সেশন তৈরি করা] ---
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    async with bot.conversation(event.chat_id) as conv:
        await conv.send_message("👋 সেশন তৈরির জন্য একটি নাম দিন (যেমন: user1):")
        name = (await conv.get_response()).text
        
        await conv.send_message("📞 আপনার ফোন নম্বর দিন (+880...):")
        phone = (await conv.get_response()).text
        
        client = TelegramClient(os.path.join(SESSION_DIR, name), API_ID, API_HASH)
        await client.connect()
        
        try:
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                await conv.send_message("📩 OTP কোডটি দিন:")
                code = (await conv.get_response()).text
                try:
                    await client.sign_in(phone, code)
                except errors.SessionPasswordNeededError:
                    await conv.send_message("🔐 2FA পাসওয়ার্ড দিন:")
                    password = (await conv.get_response()).text
                    await client.sign_in(password=password)
            
            await conv.send_message(f"✅ সেশন `{name}` সফলভাবে তৈরি হয়েছে!")
        except Exception as e:
            await conv.send_message(f"❌ এরর: {str(e)}")
        finally:
            await client.disconnect()

# উভয় সার্ভিস একসাথে চালানো
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

app = FastAPI(lifespan=lifespan)
user_sessions = {}

@app.get("/")
async def home():
    import pyrogram
    return {"status": "online", "version": pyrogram.__version__}

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

        # Create Star Gift Invoice
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
        state["phone"] = m.text
        path = os.path.join(SESSION_DIR, state["name"])
        temp_client = Client(path, api_id=API_ID, api_hash=API_HASH)
        await temp_client.connect()
        code = await temp_client.send_code(m.text)
        state.update({"hash": code.phone_code_hash, "client": temp_client, "step": "otp"})
        await m.reply("📩 OTP Sent!")
    elif state["step"] == "otp":
        try:
            await state["client"].sign_in(state["phone"], state["hash"], m.text)
            await m.reply(f"✅ Session `{state['name']}` saved!")
            await state["client"].disconnect()
            del user_sessions[user_id]
        except errors.SessionPasswordNeeded:
            state["step"] = "2fa"
            await m.reply("🔐 Enter 2FA Password:")
    elif state["step"] == "2fa":
        await state["client"].check_password(m.text)
        await m.reply(f"✅ Session `{state['name']}` saved!")
        await state["client"].disconnect()
        del user_sessions[user_id]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

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


