import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from datetime import datetime
import pytz
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console(force_terminal=True, legacy_windows=False)

class ConsoleUI:

    def __init__(self):
        self.local_tz = pytz.timezone("Asia/Bangkok")

    def render_dashboard(self, symbol: str, price_info: dict, account_info: dict, 
                         news_status: dict, scalper_result: dict, session_desc: str):
        now_str = datetime.now(self.local_tz).strftime("%Y-%m-%d %H:%M:%S")

        # Top Header
        header_text = Text()
        header_text.append("[*] GOLD PRECISION SCALPING ASSISTANT (Exness MT5)\n", style="bold yellow")
        header_text.append(f"[*] BKK Time: {now_str} | Market: {session_desc}", style="cyan")

        # Account & Market Info Table
        info_table = Table(show_header=True, header_style="bold magenta", expand=True)
        info_table.add_column("Symbol", style="bold cyan", justify="center")
        info_table.add_column("Bid Price", justify="right")
        info_table.add_column("Ask Price", justify="right")
        info_table.add_column("Spread (Pips)", justify="center")
        info_table.add_column("Balance", justify="right", style="green")
        info_table.add_column("Equity", justify="right", style="bold green")

        bid = f"${price_info.get('bid', 0.0):.2f}" if price_info else "N/A"
        ask = f"${price_info.get('ask', 0.0):.2f}" if price_info else "N/A"
        spread = f"{price_info.get('spread_pips', 0.0)} pips" if price_info else "N/A"
        balance = f"${account_info.get('balance', 0.0):,.2f}" if account_info else "N/A"
        equity = f"${account_info.get('equity', 0.0):,.2f}" if account_info else "N/A"

        info_table.add_row(symbol or "Searching...", bid, ask, spread, balance, equity)

        # News Shield Status Panel
        news_style = "bold green" if news_status.get("is_safe", True) else "bold red"
        news_msg = news_status.get("message", "N/A")
        news_panel = Panel(
            f"[{news_style}]STATUS: {news_status.get('status', 'UNKNOWN')}[/{news_style}]\n{news_msg}",
            title="[!] Forex Factory News Shield (USD Red News)",
            border_style="red" if not news_status.get("is_safe", True) else "green"
        )

        # Signal Status Panel
        sig = scalper_result.get("signal", "SCANNING")
        stars = scalper_result.get("stars", "")
        trade = scalper_result.get("trade_setup")
        reasons = scalper_result.get("reasons", [])

        if sig == "BUY":
            border = "green"
            sig_header = f"[+] BUY SIGNAL TRIGGERED {stars}"
        elif sig == "SELL":
            border = "red"
            sig_header = f"[-] SELL SIGNAL TRIGGERED {stars}"
        else:
            border = "blue"
            sig_header = "[*] MARKET SCANNING / WAITING FOR SNIPER SETUP"

        sig_lines = [sig_header, ""]
        if trade:
            sig_lines.append(f"  Entry Zone: ${trade['entry']:.2f}")
            sig_lines.append(f"  Stop Loss:  ${trade['sl']:.2f} ({trade['sl_pips']} pips)")
            sig_lines.append(f"  Target TP1: ${trade['tp1']:.2f} (1:1.5 RR)")
            sig_lines.append(f"  Target TP2: ${trade['tp2']:.2f} ({trade['risk_reward']})")
            sig_lines.append(f"  Rec. Lot:   {trade['recommended_lot']} (Risk ${trade['risk_usd']:.2f})")
            sig_lines.append("")

        sig_lines.append(f"Market Trend: {scalper_result.get('htf_trend', 'N/A')}")
        if reasons:
            sig_lines.append("Confluence Factors:")
            for r in reasons:
                sig_lines.append(f"  * {r}")

        signal_panel = Panel(
            "\n".join(sig_lines),
            title="[+] Precision Signal Engine",
            border_style=border
        )

        console.clear()
        console.print(Panel(header_text, border_style="yellow"))
        console.print(info_table)
        console.print(news_panel)
        console.print(signal_panel)
