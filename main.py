import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pyrogram import Client, raw, errors
from dotenv import load_dotenv

# এনভায়রনমেন্ট ভেরিয়েবল লোড করা
load_dotenv()

app = FastAPI()

# Railway Variables থেকে ডাটা নিবে
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

@app.get("/")
async def root():
    return {"status": "running", "message": "Telegram Gift API is online!"}

@app.get("/send-gift")
async def send_gift_api(
    request: Request, 
    gift_id: int, 
    target: str, 
    session: str, 
    message: str = "Enjoy!"
):
    if not API_ID or not API_HASH:
        return JSONResponse(status_code=500, content={"error": "API_ID or API_HASH not set in environment variables"})

    # সেশন ফাইল রেলওয়ের স্টোরেজে তৈরি হবে
    client = Client(session, api_id=int(API_ID), api_hash=API_HASH)
    
    try:
        await client.start()
        
        try:
            peer = await client.resolve_peer(target)
        except (errors.PeerIdInvalid, errors.UsernameNotOccupied):
            return JSONResponse(status_code=400, content={
                "status": "error", "code": "USER_NOT_FOUND", 
                "message": "User not found. They must DM you first."
            })

        invoice = raw.types.InputInvoiceStarGift(
            peer=peer, gift_id=gift_id,
            message=raw.types.TextWithEntities(text=message, entities=[])
        )

        try:
            form = await client.invoke(raw.functions.payments.GetPaymentForm(invoice=invoice))
            form_id = getattr(form, "form_id", None) or getattr(form, "id", None)
            await client.invoke(raw.functions.payments.SendStarsForm(form_id=form_id, invoice=invoice))
        except errors.BalanceTooLow:
            return JSONResponse(status_code=402, content={
                "status": "error", "code": "INSUFFICIENT_BALANCE", 
                "message": "You do not have enough Telegram Stars."
            })

        return {"status": "success", "message": f"Gift sent to {target}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "details": str(e)})
    finally:
        if client.is_connected:
            await client.stop()
            