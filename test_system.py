# ==========================================================
# Self-Diagnostic & Verification Suite for Gold Bot (AI & Macro)
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import yaml

from core.news_engine import NewsEngine
from strategy.indicators import IndicatorEngine
from strategy.smc_engine import SMCEngine
from strategy.risk_manager import RiskManager
from strategy.macro_levels import MacroLevelsEngine
from strategy.ai_candle_classifier import AICandleClassifier
from strategy.price_action_scalper import PriceActionScalper

class TestGoldBot(unittest.TestCase):

    def setUp(self):
        with open('config.yaml', 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    def test_news_engine(self):
        print('\n--- Testing NewsEngine ---')
        engine = NewsEngine(self.config)
        shield = engine.check_shield()
        print('Status:', shield['status'])
        print('Message:', shield['message'])
        self.assertIn('is_safe', shield)
        self.assertIn('status', shield)

    def test_macro_levels_engine(self):
        print('\n--- Testing MacroLevelsEngine ---')
        macro = MacroLevelsEngine(tolerance_pips=25.0)
        
        times = [datetime(2026, 7, 1) + timedelta(days=i) for i in range(30)]
        data = []
        for i in range(30):
            if i == 15:
                data.append({'open': 2520.0, 'high': 2550.0, 'low': 2515.0, 'close': 2540.0})
            elif i == 20:
                data.append({'open': 2470.0, 'high': 2475.0, 'low': 2450.0, 'close': 2460.0})
            elif i == 28:
                data.append({'open': 2495.0, 'high': 2510.0, 'low': 2490.0, 'close': 2505.0})
            else:
                data.append({'open': 2500.0, 'high': 2508.0, 'low': 2495.0, 'close': 2502.0})

        df_d1 = pd.DataFrame(data, index=times)
        macro.update_from_candles(df_d1)
        
        print('Calculated Macro Levels:', macro.levels)
        self.assertEqual(macro.levels['pdh'], 2510.0)
        self.assertEqual(macro.levels['pdl'], 2490.0)

        match = macro.check_macro_confluence(2510.50, pip_size=0.10)
        print('Proximity match at $2510.50:', match['description'])
        self.assertTrue(match['is_at_key_level'])
        self.assertEqual(match['zone_type'], 'RESISTANCE')
        print('Macro Levels Engine: PASSED')

    def test_ai_candle_classifier(self):
        print('\n--- Testing AICandleClassifier ---')
        candle = {'lower_wick_pct': 65.0, 'upper_wick_pct': 10.0, 'is_pinbar_bull': True, 'is_displacement': False}
        sweep = {'sweep_type': 'BULLISH_SWEEP', 'sweep_level': 2480.0}
        macro = {'is_at_key_level': True, 'zone_type': 'SUPPORT', 'score_bonus': 3}
        mtf = {'m15_trend': 'BULLISH', 'h1_trend': 'BULLISH', 'above_ema50': True}

        eval_res = AICandleClassifier.evaluate_setup(
            action='BUY',
            candle_metrics=candle,
            sweep_metrics=sweep,
            macro_metrics=macro,
            mtf_metrics=mtf,
            fvg_present=True,
            session_active=True
        )
        print('AI Evaluation Win Prob:', eval_res['win_probability'], '% | Grade:', eval_res['grade'])
        self.assertTrue(eval_res['approved'])
        self.assertGreaterEqual(eval_res['win_probability'], 85.0)
        self.assertEqual(eval_res['grade'], 'GRADE_A_PLUS_SNIPER')
        print('AI Candle Classifier: PASSED')

    def test_risk_manager(self):
        print('\n--- Testing RiskManager ---')
        rm = RiskManager(self.config)
        trade = rm.calculate_trade_levels('BUY', 2500.0, 2498.0, 0.10, account_balance=5000.0)
        self.assertTrue(trade['is_valid'])
        self.assertGreater(trade['recommended_lot'], 0)
        self.assertEqual(trade['entry'], 2500.0)
        self.assertEqual(trade['sl'], 2497.80)
        print('Risk Manager Calculation: PASSED')

if __name__ == '__main__':
    unittest.main()
