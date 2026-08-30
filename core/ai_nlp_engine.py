# ==========================================================
# Natural Language Conversational Engine for Gold Trading
# ==========================================================
import logging
import requests
import json

logger = logging.getLogger("AINLPEngine")

class AINLPEngine:
    """
    Handles natural language Thai/English questions from the user on Telegram.
    Supports:
    1. Built-in Smart NLP Intent & Context Processor (100% Free, zero setup)
    2. Google Gemini Generative AI (Optional 100% Free API for deep conversational Q&A)
    """

    def __init__(self, gemini_api_key: str = ""):
        self.gemini_key = gemini_api_key.strip()

    def process_message(self, user_text: str, market_context: dict) -> str:
        """
        Interprets natural human questions and replies conversationally.
        """
        text = user_text.strip().lower()

        # If Gemini API key is configured, use full LLM intelligence
        if self.gemini_key:
            reply = self._ask_gemini(user_text, market_context)
            if reply:
                return reply

        # Built-in Smart Natural Language Processing (Thai & English)
        return self._smart_rule_based_response(text, market_context)

    def _smart_rule_based_response(self, text: str, ctx: dict) -> str:
        price = ctx.get("price", {})
        news = ctx.get("news", {})
        macro = ctx.get("macro", {})
        scalp = ctx.get("scalper_result", {})
        acc = ctx.get("account", {})

        mid = price.get("mid", 0.0)
        spread = price.get("spread_pips", 0.0)
        news_msg = news.get("message", "ไม่มีข้อมูลข่าว")
        is_safe = news.get("is_safe", True)
        trend = scalp.get("htf_trend", "NEUTRAL")
        macro_desc = scalp.get("macro_zone", "None")

        # 1. Intent: ถามราคา / ตอนนี้ทองเท่าไหร่
        if any(w in text for w in ["ราคา", "เท่าไหร่", "กี่บาท", "price", "ทองตอนนี้", "วิ่งถึงไหน"]):
            return (
                f"🪙 <b>ราคาทองคำปัจจุบัน (XAUUSD):</b>\n"
                f"ราคาซื้อ (Bid): <b>${price.get('bid', 0.0):.2f}</b> | ราคาขาย (Ask): <b>${price.get('ask', 0.0):.2f}</b>\n"
                f"📊 ค่า Spread: <b>{spread} pips</b>\n"
                f"🏛️ โซนราคา: {macro_desc}\n\n"
                f"💡 คุณสามารถถามว่า <i>'วิเคราะห์ให้หน่อย'</i> หรือ <i>'น่าเข้าไหม'</i> ได้เลยครับ!"
            )

        # 2. Intent: ถามข่าว / ข่าวกล่องแดง / มีข่าวไหม / กี่โมง
        if any(w in text for w in ["ข่าว", "กล่องแดง", "news", "กี่โมง", "คืนนี้มีอะไร", "cpi", "nfp", "fomc", "ระวังอะไร"]):
            status_text = "🟢 <b>ปลอดภัยสำหรับการเทรด</b> (ไม่มีข่าวกระชากในระยะสั้น)" if is_safe else "🚨 <b>กำลังมีข่าวกล่องแดง! แนะนำให้หลีกเลี่ยงการเปิดออเดอร์</b>"
            return (
                f"🛡️ <b>รายงานข่าวเศรษฐกิจ Forex Factory:</b>\n"
                f"สถานะ: {status_text}\n"
                f"รายละเอียด: {news_msg}\n\n"
                f"💡 บอทจะหยุดส่งสัญญาณล่วงหน้า 30 นาทีก่อนข่าวออก เพื่อไม่ให้พอร์ตถูกลากครับ"
            )

        # 3. Intent: วิเคราะห์ / น่าเข้าไหม / บายได้ไหม / เซลได้ไหม / สัญญาณ
        if any(w in text for w in ["วิเคราะห์", "เข้าได้ยัง", "น่าเข้าไหม", "ซื้อได้ไหม", "ขายได้ไหม", "บายได้ไหม", "เซลได้ไหม", "signal", "สแกน", "แผนวันนี้", "ทำไงดี", "ทิศทาง", "เล่นทางไหน"]):
            sig = scalp.get("signal", "WAIT")
            trade = scalp.get("trade_setup")
            win_prob = scalp.get("win_probability", 0.0)

            if sig in ["BUY", "SELL"] and trade:
                action_th = "ซื้อ (BUY)" if sig == "BUY" else "ขาย (SELL)"
                return (
                    f"🎯 <b>ผลการวิเคราะห์สด: แนะนำเปิด {action_th} ⭐⭐⭐⭐⭐</b>\n"
                    f"🧠 ความน่าจะเป็นชนะ (AI Win Prob): <b>{win_prob:.1f}%</b>\n\n"
                    f"📍 <b>จุดเข้า (Entry):</b> ${trade['entry']:.2f}\n"
                    f"🛑 <b>จุดตัดขาดทุน (SL):</b> ${trade['sl']:.2f} ({trade['sl_pips']} pips)\n"
                    f"🎯 <b>เป้าทำกำไร (TP1):</b> ${trade['tp1']:.2f} | <b>(TP2):</b> ${trade['tp2']:.2f}\n"
                    f"⚖️ <b>Lot แนะนำ:</b> {trade['recommended_lot']} Lot\n\n"
                    f"💡 <i>เหตุผล: ตรวจพบการกวาดสภาพคล่อง (Liquidity Sweep) + แท่งเทียน Rejection คอนเฟิร์มตรงโซน</i>"
                )
            else:
                reasons = "\n".join([f"  • {r}" for r in scalp.get("reasons", [])])
                return (
                    f"🔍 <b>ผลการวิเคราะห์ตลาดทองคำ ณ ตอนนี้:</b>\n"
                    f"สถานะ: <b><u>ยังไม่แนะนำให้เข้าออเดอร์ (WAIT)</u></b>\n"
                    f"📈 เทรนด์ภาพใหญ่: <b>{trend}</b>\n"
                    f"🏛️ โซน Macro: {macro_desc}\n\n"
                    f"💡 <b>เหตุผลทางเทคนิค:</b>\n{reasons}\n\n"
                    f"⏳ <i>บอทกำลังเฝ้ารอจังหวะสไนเปอร์เกรด A+ ให้คุณอยู่ เมื่อโครงสร้างสวยงามจะส่งแจ้งเตือนทันทีครับ</i>"
                )

        # 4. Intent: แนวรับ / แนวต้าน / ไฮเดิม / โลว์เดิม / กรอบราคา
        if any(w in text for w in ["แนวรับ", "แนวต้าน", "รับต้าน", "ไฮเดิม", "โลว์เดิม", "กรอบ", "หลุด", "macro", "support", "resistance"]):
            pmh = macro.get("pmh", 0.0)
            pml = macro.get("pml", 0.0)
            pwh = macro.get("pwh", 0.0)
            pwl = macro.get("pwl", 0.0)
            pdh = macro.get("pdh", 0.0)
            pdl = macro.get("pdl", 0.0)
            return (
                f"🏛️ <b>แผนที่แนวรับ-แนวต้านสำคัญระดับ Macro:</b>\n"
                f"🪙 <b>ราคาปัจจุบัน:</b> <code>${mid:.2f}</code>\n\n"
                f"📅 <b>แนวระดับเดือน (Monthly):</b>\n"
                f"  • ต้านสูงสุดเดือนก่อน (PMH): <b>${pmh:.2f}</b>\n"
                f"  • รับต่ำสุดเดือนก่อน (PML): <b>${pml:.2f}</b>\n\n"
                f"📆 <b>แนวระดับสัปดาห์ (Weekly):</b>\n"
                f"  • ต้านสัปดาห์ก่อน (PWH): <b>${pwh:.2f}</b>\n"
                f"  • รับสัปดาห์ก่อน (PWL): <b>${pwl:.2f}</b>\n\n"
                f"🕒 <b>แนวระดับวัน (Daily):</b>\n"
                f"  • ต้านเมื่อวาน (PDH): <b>${pdh:.2f}</b>\n"
                f"  • รับเมื่อวาน (PDL): <b>${pdl:.2f}</b>\n\n"
                f"💡 <i>เมื่อราคาเคลื่อนที่เข้าใกล้แนวเหล่านี้ มักเกิดการดีดตัวแรงหรือการกวาดกิน Stop Loss ครับ</i>"
            )

        # 5. Intent: เงินในพอร์ต / ทุน / บาลานซ์ / สถานะ
        if any(w in text for w in ["พอร์ต", "เงิน", "บาลานซ์", "ทุน", "balance", "equity", "สถานะ", "status", "กี่ดอล"]):
            return (
                f"📊 <b>สถานะบัญชีเทรดของคุณ:</b>\n"
                f"👤 บัญชี: <b>#{acc.get('login', 'N/A')} ({acc.get('server', 'N/A')})</b>\n"
                f"💵 ยอดบาลานซ์: <b>${acc.get('balance', 0.0):,.2f}</b>\n"
                f"💎 ยอดเงินสุทธิ (Equity): <b>${acc.get('equity', 0.0):,.2f}</b>\n"
                f"⚡ Leverage: <b>1:{acc.get('leverage', 0)}</b>"
            )

        # 6. Intent: คำทักทาย / คุยทั่วไป
        if any(w in text for w in ["สวัสดี", "หวัดดี", "hi", "hello", "ดีครับ", "สบายดีไหม", "ช่วยอะไรได้บ้าง"]):
            return (
                f"สวัสดีครับ! ผมคือผู้ช่วยเทรดทองคำสไนเปอร์ของคุณ 🪙🤖\n\n"
                f"คุณสามารถพิมพ์ถามผมเป็นภาษามนุษย์ได้สบายๆ เลยครับ เช่น:\n"
                f"• <i>'ทองตอนนี้เป็นยังไงบ้าง'</i>\n"
                f"• <i>'วิเคราะห์กราฟให้หน่อย น่าเข้าไหม'</i>\n"
                f"• <i>'คืนนี้มีข่าวอะไรต้องระวังไหม'</i>\n"
                f"• <i>'แนวรับแนวต้านสำคัญอยู่ตรงไหน'</i>\n"
                f"• <i>'เช็คเงินในพอร์ตให้หน่อย'</i>"
            )

        # Default fallback: Comprehensive market snapshot
        return (
            f"รับทราบครับ! ตอนนี้ราคาทองคำอยู่ที่ <b>${mid:.2f}</b> (Spread: {spread} pips)\n"
            f"📈 เทรนด์ภาพใหญ่: <b>{trend}</b> | ข่าว: <b>{news.get('status', 'SAFE')}</b>\n\n"
            f"💡 คุณสามารถถามผมได้ เช่น:\n"
            f"  • <i>'วิเคราะห์ให้หน่อย'</i>\n"
            f"  • <i>'แนวรับต้านอยู่ตรงไหน'</i>\n"
            f"  • <i>'มีข่าวไหม'</i>"
        )

    def _ask_gemini(self, user_prompt: str, ctx: dict) -> str:
        """Calls Google Gemini API for deep AI conversation."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
        
        system_instruction = (
            "You are an elite, professional Gold (XAUUSD) Precision Trading Assistant. "
            "You chat with the trader in polite, friendly Thai language. "
            "You always prioritize risk management, tight Stop Loss, and capital preservation. "
            f"CURRENT MARKET CONTEXT:\n{json.dumps(ctx, default=str, ensure_ascii=False)}"
        )

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"Context: {system_instruction}\n\nTrader's Question: {user_prompt}"}]}
            ]
        }

        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                reply = data["candidates"][0]["content"]["parts"][0]["text"]
                return reply
        except Exception as e:
            logger.warning(f"Gemini API call error: {e}")

        return ""
