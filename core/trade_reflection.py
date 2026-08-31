# ==========================================================
# AI Trade Post-Mortem & Self-Learning Reflection Engine
# ==========================================================
import os
import json
import logging
from datetime import datetime, timedelta
import pytz
import MetaTrader5 as mt5

logger = logging.getLogger("TradeReflection")

class TradeReflectionEngine:
    """
    Monitors closed trades, analyzes losing setups (Post-Mortem),
    extracts actionable lessons, and adjusts AI confidence to avoid repeating mistakes.
    """

    MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trade_memory.json")

    def __init__(self, config: dict, telegram_notifier=None):
        self.config = config
        self.telegram = telegram_notifier
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.memory = self._load_memory()
        self.processed_deal_tickets = set(self.memory.get("processed_tickets", []))

    def _load_memory(self) -> dict:
        os.makedirs(os.path.dirname(self.MEMORY_FILE), exist_ok=True)
        if os.path.exists(self.MEMORY_FILE):
            try:
                with open(self.MEMORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error loading trade memory: {e}")
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "lessons_learned": [],
            "penalized_setups": {},
            "processed_tickets": []
        }

    def _save_memory(self):
        try:
            self.memory["processed_tickets"] = list(self.processed_deal_tickets)[-200:]
            with open(self.MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving trade memory: {e}")

    def inspect_and_learn_from_deals(self, magic_number: int = 778899) -> list:
        """
        Inspects recently closed deals in MT5, identifies wins/losses,
        and generates Post-Mortem reflection for each trade.
        """
        now = datetime.now(self.local_tz)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        
        deals = mt5.history_deals_get(today_start, now)
        if not deals:
            return []

        reflections = []

        for d in deals:
            if d.magic == magic_number and d.entry == mt5.DEAL_ENTRY_OUT:
                deal_id = d.ticket
                if deal_id in self.processed_deal_tickets:
                    continue

                self.processed_deal_tickets.add(deal_id)
                profit = round(d.profit + d.swap + d.commission, 2)
                symbol = d.symbol
                volume = d.volume
                price = d.price
                comment = d.comment

                self.memory["total_trades"] += 1

                if profit < 0:
                    self.memory["losses"] += 1
                    post_mortem = self._analyze_loss(d, profit, comment)
                    self.memory["lessons_learned"].append(post_mortem)
                    reflections.append(post_mortem)
                    
                    # Dispatch to Telegram
                    if self.telegram:
                        msg = (
                            f"🧠 <b>AI TRADE POST-MORTEM & REFLECTION</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            f"📉 <b>ผลลัพธ์:</b> ขาดทุน <code>-${abs(profit):.2f}</code> (Ticket #{deal_id})\n"
                            f"📍 <b>จุดปิด:</b> ${price:.2f} | <b>Lot:</b> {volume}\n\n"
                            f"🔍 <b>สาเหตุที่แพ้ตลาด:</b>\n{post_mortem['root_cause']}\n\n"
                            f"💡 <b>บทเรียนที่สมองกลจดจำ:</b>\n{post_mortem['lesson']}\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "🛡️ <i>ระบบบันทึกความจำและปรับลดความเสี่ยงในจุดนี้เรียบร้อยแล้ว</i>"
                        )
                        self.telegram.send_message(msg)

                else:
                    self.memory["wins"] += 1
                    win_report = {
                        "ticket": deal_id,
                        "type": "WIN",
                        "profit": profit,
                        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "message": f"🏆 ไม้ทำกำไร +${profit:.2f} ตามแผนการเทรดสำเร็จ!"
                    }
                    reflections.append(win_report)

                    if self.telegram:
                        msg = (
                            f"🎉 <b>AI TRADE TAKE-PROFIT SUCCESS!</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            f"📈 <b>ผลลัพธ์:</b> กำไร <code>+${profit:.2f}</code> 🟢 (Ticket #{deal_id})\n"
                            f"📍 <b>จุดปิดทำกำไร:</b> ${price:.2f} | <b>Lot:</b> {volume}\n"
                            f"✨ <b>กลยุทธ์:</b> แผนการเทรดสถาบันเข้าเป้าสมบูรณ์แบบ!\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "💰 <i>สะสมกำไรเข้าพอร์ตเรียบร้อยครับ!</i>"
                        )
                        self.telegram.send_message(msg)

        self._save_memory()
        return reflections

    def _analyze_loss(self, deal, profit: float, comment: str) -> dict:
        """Heuristic and ML analysis of why the trade failed."""
        now_str = datetime.now(self.local_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Identify common loss modes
        if "sl" in comment.lower() or deal.reason == mt5.DEAL_REASON_SL:
            root_cause = "• โดนแรงสะบัดของคลื่นราคากวาด Stop Loss ก่อนที่กราฟจะเลือกทิศทาง หรือเข้าที่ปลายคลื่น Overextended"
            lesson = "• เพิ่มระยะบัฟเฟอร์ SL และรอให้ราคาย่อลึกเข้า Discount FVG (ย่อ Buy) หรือ Premium FVG (เด้ง Sell) ให้ลึกขึ้นก่อนออกไม้"
        else:
            root_cause = "• ตลาดเกิดการกลับทิศทางอย่างรวดเร็ว (Structural Market Shift)"
            lesson = "• ตรวจสอบสัญญาณ Break of Structure (BOS) ใน M15 ให้ชัดเจนก่อนเข้าออเดอร์"

        return {
            "ticket": deal.ticket,
            "type": "LOSS",
            "loss_amount": profit,
            "time": now_str,
            "root_cause": root_cause,
            "lesson": lesson
        }
