"""
Screener configuration with all default thresholds from the breakout definition.
All values are overridable via API query parameters.
"""

from dataclasses import dataclass, field
from typing import List
import os

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "screener.db")
NIFTY500_CSV = os.path.join(DATA_DIR, "nifty500.csv")


@dataclass
class ScreenerConfig:
    """Configuration for the breakout screener."""

    # --- Resistance Mode ---
    # Options: "52_WEEK_HIGH", "N_DAY_HIGH", "SWING_HIGH"
    resistance_mode: str = "52_WEEK_HIGH"
    n_day_lookback: int = 252  # Used when mode is N_DAY_HIGH

    # --- Volume Confirmation ---
    volume_multiplier: float = 2.0  # Today's volume >= multiplier × avg volume
    volume_lookback: int = 20  # Period for average volume calculation

    # --- Near Breakout Radar ---
    scan_type: str = "BROKEN_OUT"  # "BROKEN_OUT" or "NEAR_BREAKOUT"
    near_breakout_pct: float = 2.0  # Within X% below resistance

    # --- Trade Planning & Position Sizing ---
    entry_buffer_pct: float = 0.1  # % buffer above resistance for entry trigger
    default_stop_loss_pct: float = 3.5  # Fallback SL % if swing low is too far
    risk_per_trade_inr: float = 5000.0  # Maximum risk per trade in ₹
    risk_reward_ratio: float = 2.0  # R:R ratio for Target 1

    # --- Filters ---
    min_price: float = 50.0  # Minimum stock price (₹)
    min_turnover_cr: float = 1.0  # Minimum avg daily turnover in ₹ Crores
    require_above_200dma: bool = True  # Close must be above 200-day SMA
    rsi_filter_enabled: bool = False  # Whether to apply RSI filter
    rsi_threshold: float = 60.0  # Minimum RSI (when filter is enabled)

    # --- Swing High Detection ---
    swing_high_left: int = 5  # Bars to the left for pivot detection
    swing_high_right: int = 5  # Bars to the right for pivot detection

    # --- Near Breakout Radar ---
    near_breakout_pct_max: float = 3.0  # Max % below resistance (e.g. within 3%)
    near_breakout_pct_min: float = 0.0  # Min % below resistance
    entry_buffer_pct: float = 0.1       # Entry trigger buffer above resistance (%)
    default_max_risk_rs: float = 5000.0 # Default max risk in ₹ per trade

    # --- Strength Scoring Weights (must sum to 1.0) ---
    weight_volume: float = 0.30
    weight_price_gap: float = 0.25
    weight_trend: float = 0.20
    weight_consolidation: float = 0.15
    weight_rsi: float = 0.10

    # --- Backtest Settings ---
    forward_return_days: List[int] = field(
        default_factory=lambda: [5, 10, 20, 30]
    )
    backtest_lookback_years: int = 1  # How many years of history to backtest

    # --- Data Settings ---
    data_download_period: str = "2y"  # yfinance period string (2yr for 200DMA lookback)

    def to_dict(self) -> dict:
        """Serialize config to dict for API responses."""
        return {
            "resistance_mode": self.resistance_mode,
            "n_day_lookback": self.n_day_lookback,
            "volume_multiplier": self.volume_multiplier,
            "volume_lookback": self.volume_lookback,
            "scan_type": self.scan_type,
            "near_breakout_pct": self.near_breakout_pct,
            "entry_buffer_pct": self.entry_buffer_pct,
            "default_stop_loss_pct": self.default_stop_loss_pct,
            "risk_per_trade_inr": self.risk_per_trade_inr,
            "risk_reward_ratio": self.risk_reward_ratio,
            "min_price": self.min_price,
            "min_turnover_cr": self.min_turnover_cr,
            "require_above_200dma": self.require_above_200dma,
            "rsi_filter_enabled": self.rsi_filter_enabled,
            "rsi_threshold": self.rsi_threshold,
            "swing_high_left": self.swing_high_left,
            "swing_high_right": self.swing_high_right,
            "weight_volume": self.weight_volume,
            "weight_price_gap": self.weight_price_gap,
            "weight_trend": self.weight_trend,
            "weight_consolidation": self.weight_consolidation,
            "weight_rsi": self.weight_rsi,
            "forward_return_days": self.forward_return_days,
            "backtest_lookback_years": self.backtest_lookback_years,
            "data_download_period": self.data_download_period,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenerConfig":
        """Create config from a dict, using defaults for missing keys."""
        defaults = cls()
        return cls(
            resistance_mode=data.get("resistance_mode", defaults.resistance_mode),
            n_day_lookback=int(data.get("n_day_lookback", defaults.n_day_lookback)),
            volume_multiplier=float(
                data.get("volume_multiplier", defaults.volume_multiplier)
            ),
            volume_lookback=int(
                data.get("volume_lookback", defaults.volume_lookback)
            ),
            scan_type=data.get("scan_type", defaults.scan_type),
            near_breakout_pct=float(data.get("near_breakout_pct", defaults.near_breakout_pct)),
            entry_buffer_pct=float(data.get("entry_buffer_pct", defaults.entry_buffer_pct)),
            default_stop_loss_pct=float(data.get("default_stop_loss_pct", defaults.default_stop_loss_pct)),
            risk_per_trade_inr=float(data.get("risk_per_trade_inr", defaults.risk_per_trade_inr)),
            risk_reward_ratio=float(data.get("risk_reward_ratio", defaults.risk_reward_ratio)),
            min_price=float(data.get("min_price", defaults.min_price)),
            min_turnover_cr=float(
                data.get("min_turnover_cr", defaults.min_turnover_cr)
            ),
            require_above_200dma=bool(
                data.get("require_above_200dma", defaults.require_above_200dma)
            ),
            rsi_filter_enabled=bool(
                data.get("rsi_filter_enabled", defaults.rsi_filter_enabled)
            ),
            rsi_threshold=float(
                data.get("rsi_threshold", defaults.rsi_threshold)
            ),
            swing_high_left=int(
                data.get("swing_high_left", defaults.swing_high_left)
            ),
            swing_high_right=int(
                data.get("swing_high_right", defaults.swing_high_right)
            ),
            weight_volume=float(
                data.get("weight_volume", defaults.weight_volume)
            ),
            weight_price_gap=float(
                data.get("weight_price_gap", defaults.weight_price_gap)
            ),
            weight_trend=float(data.get("weight_trend", defaults.weight_trend)),
            weight_consolidation=float(
                data.get("weight_consolidation", defaults.weight_consolidation)
            ),
            weight_rsi=float(data.get("weight_rsi", defaults.weight_rsi)),
            forward_return_days=data.get(
                "forward_return_days", defaults.forward_return_days
            ),
            backtest_lookback_years=int(
                data.get(
                    "backtest_lookback_years", defaults.backtest_lookback_years
                )
            ),
            data_download_period=data.get(
                "data_download_period", defaults.data_download_period
            ),
        )
