import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pyrogram import Client, filters, errors, raw
from pyrogram.types import Message
from dotenv import load_dotenv
import uvicorn

# এনভায়রনমেন্ট ভেরিয়েবল লোড
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ভলিউম পাথ (পার্মানেন্ট স্টোরেজ)
SESSION_DIR = "/data/sessions"
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)

app = FastAPI()
# বটের নিজস্ব সেশনও ভলিউমে থাকবে
bot = Client(os.path.join(SESSION_DIR, "manager_bot"), api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_sessions = {}

# --- [বট সেকশন: সেশন তৈরি করা] ---
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message: Message):
    await message.reply("👋 একটি ইউনিক নাম দিন (যেমন: `user1`) সেশন তৈরির জন্য।")

@bot.on_message(filters.text & filters.private)
async def handle_auth(client, message: Message):
    user_id = message.from_user.id
    text = message.text

    if user_id not in user_sessions:
        session_name = text.replace(" ", "_").strip()
        user_sessions[user_id] = {"name": session_name, "step": "phone"}
        await message.reply(f"📁 সেশন নাম: `{session_name}`\nএখন ফোন নম্বর দিন (যেমন: +88017...)।")
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
            await message.reply(f"✅ সেশন `{state['name']}` সফলভাবে তৈরি ও সেভ হয়েছে!")
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

# --- [API সেকশন: গিফট পাঠানো] ---
@app.get("/send-gift")
async def send_gift_api(gift_id: int, target: str, session: str, message: str = "Enjoy!"):
    # ভলিউম থেকে সেশন ফাইল খুঁজবে
    session_path = os.path.join(SESSION_DIR, session)
    if not os.path.exists(f"{session_path}.session"):
        return JSONResponse(status_code=404, content={"error": "Session file not found in storage!"})

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

# --- [রান করার কমান্ড] ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(bot.start()) 
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
