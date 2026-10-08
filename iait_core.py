"""IAIT v4 · núcleo. Reemplaza tu iait_core.py anterior (misma interfaz que usa iait_monitor.py).
Cambios: (1) sin block_ratio estimado, 4 variables independientes; (2) filtro de corrección previa;
(3) spread HY a 5 días; (4) el warm-up llena el historial para que la divergencia funcione."""
import math
import logging
from collections import deque
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf


@dataclass
class MarketMetrics:
    dix: float
    gex: float
    vix_ts: float
    hy_spread_change: float            # cambio a 5 días, en pb
    price: Optional[float] = None
    ema20: Optional[float] = None
    previous_high: Optional[float] = None
    volume: Optional[float] = None
    volume_ma20: Optional[float] = None
    rsi5: Optional[float] = None
    drawdown_10d: Optional[float] = None   # caída máx. de SPY vs su máximo de 60d, últimos 10 días (%)
    vix_ts_max10: Optional[float] = None   # pico de VIX/VIX3M en los últimos 10 días


class RollingStats:
    def __init__(self, window: int = 60):
        self.values = deque(maxlen=window)

    def add(self, v: float):
        if v is not None and math.isfinite(v):
            self.values.append(v)

    @property
    def count(self):
        return len(self.values)

    @property
    def mean(self):
        return sum(self.values) / len(self.values) if self.values else 0.0

    @property
    def std(self):
        n = len(self.values)
        if n < 2:
            return 1.0
        mu = self.mean
        return max(math.sqrt(sum((x - mu) ** 2 for x in self.values) / (n - 1)), 1e-6)

    def zscore(self, v: float) -> float:
        return (v - self.mean) / self.std


class IAITOptimizerV2:
    KEYS = ("dix", "gex", "vix_ts", "hy_spread_change")

    def __init__(self, window: int = 60):
        self.weights = {"dix": 0.30, "gex": 0.25, "vix_ts": 0.25, "hy_spread_change": 0.20}
        self.invert = {"dix": False, "gex": False, "vix_ts": True, "hy_spread_change": True}
        self.stats = {k: RollingStats(window) for k in self.KEYS}
        self.iait_history = deque(maxlen=100)
        self.hist_rows = []

    @staticmethod
    def _sig(x):
        return 1.0 / (1.0 + math.exp(-x))

    def _z(self, key, value):
        z = self.stats[key].zscore(value)
        z = -z if self.invert[key] else z
        return max(-3.0, min(3.0, z))

    def is_ready(self):
        return all(self.stats[k].count >= 30 for k in self.KEYS)

    def update_market_history(self, m: MarketMetrics):
        for k in self.KEYS:
            self.stats[k].add(getattr(m, k))

    def price_confirmation(self, m: MarketMetrics) -> Dict[str, Any]:
        t = []
        if m.price is not None and m.ema20 is not None:
            t.append(m.price > m.ema20)
        if m.price is not None and m.previous_high is not None:
            t.append(m.price > m.previous_high)
        if m.volume is not None and m.volume_ma20 is not None:
            t.append(m.volume > 1.2 * m.volume_ma20)
        if m.rsi5 is not None:
            t.append(m.rsi5 > 50)
        return {"available_tests": len(t), "positive_tests": sum(t),
                "confirmation_ratio": (sum(t) / len(t)) if t else None}

    def has_prior_stress(self, m: MarketMetrics) -> bool:
        dd = m.drawdown_10d is not None and m.drawdown_10d >= 5.0
        ts = m.vix_ts_max10 is not None and m.vix_ts_max10 >= 1.0
        return dd or ts

    def evaluate(self, m: MarketMetrics, update_history: bool = True) -> Dict[str, Any]:
        wz, pos, bd = 0.0, 0, {}
        for k in self.KEYS:
            v = getattr(m, k)
            z = self._z(k, v)
            wz += z * self.weights[k]
            pos += z >= 0.5
            bd[k] = {"raw": round(v, 4), "z_score": round(z, 3), "score": round(100 * self._sig(z), 1),
                     "weight": self.weights[k], "contribution": round(z * self.weights[k], 3)}
        raw = max(0.0, min(100.0, 50.0 + wz * 15.0))
        penalty = 8 if bd["hy_spread_change"]["z_score"] < -0.5 and bd["vix_ts"]["z_score"] < -0.5 else 0
        score = max(0.0, raw - penalty)
        pc = self.price_confirmation(m)
        confirmed = pc["confirmation_ratio"] is not None and pc["confirmation_ratio"] >= 0.5
        gate = self.has_prior_stress(m)

        # divergencia: IAIT sube vs hace 5 sesiones y RSI5 > 45
        div = {"detected": False, "type": "INSUFFICIENT_DATA"}
        if len(self.iait_history) >= 5:
            up = score > self.iait_history[-5]
            ok = up and m.rsi5 is not None and m.rsi5 > 45
            div = {"detected": bool(ok), "type": "POSITIVE_INTERNAL_DIVERGENCE" if ok else "NONE"}

        if not gate:
            level, status, action = "NEUTRAL", "⚪ SIN SETUP: no hubo corrección previa", \
                "Sin caída ≥5% ni estrés de VIX en 10 días; el IAIT no aplica. Mantener postura actual."
        elif score >= 77 and pos >= 3 and confirmed:
            level, status, action = "GREEN", "🟢 ALERTA VERDE: ACUMULACIÓN INSTITUCIONAL CONFIRMADA", \
                "Iniciar reentrada escalonada (25% / 50% / 25% del capital táctico)."
        elif score >= 77 and pos >= 3:
            level, status, action = "PRE_GREEN", "🟡 PRE-VERDE: IAIT ELEVADO SIN CONFIRMACIÓN DE PRECIO", \
                "Preparar liquidez y esperar confirmación de precio y volumen."
        elif score >= 65 and pos >= 2:
            level, status, action = "YELLOW", "🟡 ALERTA AMARILLA: ABSORCIÓN TEMPRANA DETECTADA", \
                "Monitorear a diario; primer tramo (25%) solo con confirmación técnica."
        else:
            level, status, action = "NEUTRAL", "⚪ SIN SEÑAL DE ACUMULACIÓN", "Mantener postura defensiva."
        if div["detected"]:
            status += " | DIVERGENCIA POSITIVA"
        if update_history:
            self.iait_history.append(score)
        return {"score": round(score, 2), "raw_score": round(raw, 2), "positive_variables": pos,
                "status": status, "action": action, "level": level, "stress_gate": gate,
                "price_confirmation": pc, "divergence": div, "breakdown": bd}


def drop_partial(df):
    """Quita la barra de hoy si la sesión de Nueva York aún no cerró (evita volumen parcial)."""
    if df is None or len(df) == 0:
        return df
    ny = pd.Timestamp.now(tz="America/New_York")
    last = pd.Timestamp(df.index[-1])
    last = last.tz_localize(None) if last.tzinfo is not None else last
    if last.normalize() == ny.tz_localize(None).normalize() and ny.hour < 16:
        return df.iloc[:-1]
    return df


def _naive(s):
    s = pd.to_datetime(s)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_localize(None)
    return s.astype("datetime64[ns]")


class MarketDataFetcher:
    HDR = {"User-Agent": "Mozilla/5.0"}

    @staticmethod
    def fetch_squeezemetrics() -> pd.DataFrame:
        r = requests.get("https://squeezemetrics.com/monitor/static/DIX.csv", headers=MarketDataFetcher.HDR, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df["date"] = _naive(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df["gex_billion"] = df["gex"] / 1e9
        df["dix_pct"] = df["dix"] * 100.0
        return df

    @staticmethod
    def fetch_vix_structure(days: int = 120) -> pd.DataFrame:
        d = yf.download(["^VIX", "^VIX3M"], period=f"{days}d", interval="1d", progress=False, auto_adjust=False)["Close"]
        d = drop_partial(d.dropna()).reset_index()
        d = d.rename(columns={d.columns[0]: "date"})
        d["date"] = _naive(d["date"])
        d["vix_ts"] = d["^VIX"] / d["^VIX3M"]
        return d

    @staticmethod
    def fetch_hy_spreads(days: int = 150) -> pd.DataFrame:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2",
                         headers=MarketDataFetcher.HDR, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df = df.rename(columns={df.columns[0]: "DATE", df.columns[1]: "BAMLH0A0HYM2"})
        df["DATE"] = _naive(df["DATE"])
        df["BAMLH0A0HYM2"] = pd.to_numeric(df["BAMLH0A0HYM2"], errors="coerce")
        return df.dropna().sort_values("DATE").tail(days).reset_index(drop=True)

    @staticmethod
    def fetch_spy_technical(days: int = 120) -> pd.DataFrame:
        df = yf.download("SPY", period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = drop_partial(df.copy())
        df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["previous_high"] = df["High"].shift(1).rolling(2).max()
        df["volume_ma20"] = df["Volume"].rolling(20).mean()
        d = df["Close"].diff()
        g, l = d.clip(lower=0).rolling(5).mean(), (-d.clip(upper=0)).rolling(5).mean()
        df["rsi5"] = 100 - 100 / (1 + g / l.replace(0, np.nan))
        dd = (1 - df["Close"] / df["Close"].rolling(60, min_periods=20).max()) * 100
        df["drawdown_10d"] = dd.rolling(10, min_periods=1).max()
        return df.dropna(subset=["ema20", "rsi5", "volume_ma20"])

    def get_latest_market_metrics(self, engine: IAITOptimizerV2) -> MarketMetrics:
        logging.info("Extrayendo datos de fuentes públicas...")
        sq, vix, hy, spy = (self.fetch_squeezemetrics(), self.fetch_vix_structure(),
                            self.fetch_hy_spreads(), self.fetch_spy_technical())
        hy["chg5"] = hy["BAMLH0A0HYM2"].diff(5) * 100.0
        vix["ts_max10"] = vix["vix_ts"].rolling(10, min_periods=1).max()

        f = sq[["date", "dix_pct", "gex_billion"]].tail(90).sort_values("date")
        f = pd.merge_asof(f, hy[["DATE", "chg5"]].rename(columns={"DATE": "date"}), on="date")
        f = pd.merge_asof(f, vix[["date", "vix_ts", "ts_max10"]].sort_values("date"), on="date")
        f = f.dropna()

        logging.info("Warm-up histórico (%d días)...", len(f))
        for _, r in f.iterrows():
            h = MarketMetrics(dix=float(r.dix_pct), gex=float(r.gex_billion), vix_ts=float(r.vix_ts),
                              hy_spread_change=float(r.chg5), vix_ts_max10=float(r.ts_max10))
            sc = engine.evaluate(h, update_history=True)["score"] if engine.is_ready() else None
            engine.hist_rows.append(dict(d=str(r.date.date()), dix=float(r.dix_pct), ts=float(r.vix_ts), iait=sc))
            engine.update_market_history(h)

        s, v = spy.iloc[-1], vix.iloc[-1]
        logging.info("Último dato DIX/GEX: %s", sq["date"].iloc[-1].date())
        return MarketMetrics(
            dix=float(sq["dix_pct"].iloc[-1]), gex=float(sq["gex_billion"].iloc[-1]),
            vix_ts=float(v["vix_ts"]), hy_spread_change=float(hy["chg5"].iloc[-1]),
            price=float(s["Close"]), ema20=float(s["ema20"]), previous_high=float(s["previous_high"]),
            volume=float(s["Volume"]), volume_ma20=float(s["volume_ma20"]), rsi5=float(s["rsi5"]),
            drawdown_10d=float(s["drawdown_10d"]), vix_ts_max10=float(v["ts_max10"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    eng = IAITOptimizerV2()
    res = eng.evaluate(MarketDataFetcher().get_latest_market_metrics(eng))
    print(res["status"], res["score"], res["action"])
    for k, d in res["breakdown"].items():
        print(f"{k:<18} raw {d['raw']:<9} z {d['z_score']:>6} aporte {d['contribution']:>6}")
