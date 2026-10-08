"""IAIT Monitor v7 · volumen >1.2x en todo Nueva York + noticias 24/7 en español + Telegram (hora Lima).
Todo dato personal (cartera, claves) llega por variables de entorno / GitHub Secrets; nada personal vive en el código."""
import hashlib, json, logging, os, random, re, sys, time, traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import StringIO
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from iait_core import IAITOptimizerV2, MarketDataFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
BASE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
LIMA, NY, UA = timezone(timedelta(hours=-5)), ZoneInfo("America/New_York"), {"User-Agent": "Mozilla/5.0"}
envf = lambda k, d: float(os.getenv(k) or d)
RED_T, YEL_T, EXIT_T = envf("RVOL_RED", 1.2), 1.0, envf("RVOL_EXIT", 1.1)      # rojo >=1,2x · amarillo 1,0-1,2x · verde <1,0x
TOTAL, MIN_PRICE, MIN_DAYVOL, MIN_AVGVOL = int(envf("TOTAL", 50)), envf("MIN_PRICE", 1), envf("MIN_DAYVOL", 50000), envf("MIN_AVGVOL", 100000)
EVENT_ROWS, DIAS = 15, ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
STATE = os.path.join(BASE, "state.json")
SALT = os.getenv("STATE_SALT") or os.getenv("TELEGRAM_CHAT_ID") or "iait"
hid = lambda t: hashlib.sha256((SALT + t).encode()).hexdigest()[:10]
ETFS = {"VOO", "SCHD", "QQQM", "GLD", "VTV", "SPY", "QQQ", "VXUS", "IVV", "VTI"}
ALIAS = {"NVDA": "Nvidia", "MSFT": "Microsoft", "GOOGL": "Google Alphabet", "AMZN": "Amazon", "AVGO": "Broadcom", "TSM": "TSMC",
         "MU": "Micron", "KLAC": "KLA Corporation", "CEG": "Constellation Energy", "VST": "Vistra", "BE": "Bloom Energy",
         "VRT": "Vertiv", "RKLB": "Rocket Lab", "CRWD": "CrowdStrike", "CRDO": "Credo Technology", "ALAB": "Astera Labs",
         "LLY": "Eli Lilly", "MELI": "MercadoLibre", "FLEX": "Flex Ltd", "META": "Meta Platforms", "AMD": "AMD chips",
         "TSLA": "Tesla", "ORCL": "Oracle", "NFLX": "Netflix", "IBM": "IBM", "CAT": "Caterpillar", "RTX": "RTX Raytheon",
         "PLTR": "Palantir", "INTC": "Intel", "ASML": "ASML", "AAPL": "Apple", "OKLO": "Oklo", "SMR": "NuScale"}
THEMES = {  # patrón (español) -> (tema, tickers sensibles; se cruzan con tu cartera en ejecución)
    r"nuclear|uranio|reactor": ("Energía nuclear", "CEG VST OKLO SMR CCJ BWXT TLN"),
    r"semiconductor|chips?\b|tsmc|memoria hbm|dram|litograf": ("Semiconductores", "NVDA AVGO TSM KLAC MU CRDO ALAB AMD INTC ASML MRVL"),
    r"centros? de datos|inteligencia artificial|\bia\b|hiperescala": ("Infraestructura de IA", "VRT BE CEG VST NVDA AVGO MSFT GOOGL AMZN META ORCL"),
    r"reserva federal|\bfed\b|tasas de inter|inflaci|powell|warsh": ("Política monetaria", "VOO QQQM SCHD VTV"),
    r"arancel|guerra comercial|sanciones|restricciones a la exportaci": ("Aranceles / geopolítica", "NVDA TSM KLAC AVGO MU VOO QQQM"),
    r"\boro\b|metales preciosos": ("Oro", "GLD"),
    r"cohete|satélite|espacial|spacex|nasa": ("Sector espacial", "RKLB LUNR ASTS"),
    r"ciberseguridad|ciberataque|hackeo|ransomware": ("Ciberseguridad", "CRWD PANW ZS FTNT"),
    r"obesidad|glp-1|fda|farmac": ("Salud / farmacéuticas", "LLY NVO PFE MRK"),
    r"mercado ?libre|argentina|brasil|latinoam": ("Latinoamérica", "MELI"),
    r"petróleo|opep|crudo|gas natural": ("Energía fósil", "XOM CVX OXY"),
}
LABEL = {"GREEN": "VERDE", "PRE_GREEN": "PRE-VERDE", "YELLOW": "AMARILLA", "NEUTRAL": "SIN SEÑAL", "RED": "ROJA"}
GENERAL = ["Wall Street bolsa de Nueva York", "Reserva Federal tasas de interés", "aranceles comercio Estados Unidos bolsa",
           "energía nuclear centros de datos inteligencia artificial", "semiconductores chips Nvidia TSMC", "precio del oro"]
POS = "sube suben alza récord ganancias supera aprueba acuerdo contrato adquiere compra mejora eleva impulsa crece dispara avanza".split()
NEG = "cae caen baja desploma pérdidas demanda investigación multa recorta rebaja quiebra retira riesgo sanciones despidos hunde".split()


# ---------- utilidades ----------
def lima_now(): return datetime.now(LIMA)
def ny_now(): return datetime.now(NY)
def num(x, d=0.0): return d if x is None or not np.isfinite(x) else float(x)


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}  # primera corrida o archivo dañado: se reinicia sin romper nada


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)  # escritura atómica


def env_list(k): return list(dict.fromkeys(re.findall(r"[A-Z0-9.\-]{1,10}", (os.getenv(k) or "").upper())))


def retry(fn, tries=3, wait=2):
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(wait * 2 ** i)


def tg(text, doc=None):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        logging.warning("Telegram no configurado"); return False
    base, ok, parts, cur = f"https://api.telegram.org/bot{tok}", True, [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) > 3800:
            parts.append(cur); cur = ""
        cur += line + "\n"
    parts.append(cur)
    for p in parts:
        for i in range(3):  # nunca registrar la excepción completa: contiene la URL con el token
            try:
                r = requests.post(base + "/sendMessage", data={"chat_id": chat, "text": p.strip(), "disable_web_page_preview": True}, timeout=25)
                if r.status_code == 429:
                    time.sleep(num(r.json().get("parameters", {}).get("retry_after"), 3) + 1); continue
                ok = ok and r.ok; break
            except Exception as e:
                logging.warning("Telegram: %s", type(e).__name__); time.sleep(2 * (i + 1))
        else:
            ok = False
    if doc and os.path.exists(doc):
        for i in range(2):
            try:
                with open(doc, "rb") as f:
                    ok = ok and requests.post(base + "/sendDocument", data={"chat_id": chat}, files={"document": f}, timeout=60).ok
                break
            except Exception as e:
                logging.warning("Telegram doc: %s", type(e).__name__); time.sleep(3)
    return ok


# ---------- sesión de Nueva York ----------
PROFILE = [(0, 0), (15, .07), (30, .12), (60, .20), (90, .27), (120, .33), (150, .38), (180, .43), (210, .48),
           (240, .53), (270, .58), (300, .64), (330, .71), (360, .80), (390, 1.0)]  # min desde 9:30 ET -> fracción acumulada del volumen


def session_open():
    n = ny_now(); m = n.hour * 60 + n.minute - 570
    return n.weekday() < 5 and 0 < m < 390


def session_fraction():
    if not session_open():
        return 1.0  # fuera de sesión se usa el volumen del último día completo
    n = ny_now(); m = n.hour * 60 + n.minute - 570
    f = float(np.interp(m, [p[0] for p in PROFILE], [p[1] for p in PROFILE]))
    return max(f, 0.10)


def session_text():
    return "🟢 Bolsa NY abierta (volumen ajustado al ritmo del día)" if session_open() else "⚪ Bolsa NY cerrada (se usa el último cierre)"


# ---------- universo y volumen ----------
def _fi(fi, k):
    try:
        return float(getattr(fi, k))
    except Exception:
        return float("nan")


def quote_one(t):
    try:
        fi = yf.Ticker(t).fast_info
        px, pv = _fi(fi, "last_price"), _fi(fi, "previous_close")
        return dict(sym=t, name=t, px=px, chg=(px / pv - 1) * 100 if pv else float("nan"), vol=_fi(fi, "last_volume"),
                    avg=_fi(fi, "three_month_average_volume"), mcap=_fi(fi, "market_cap"))
    except Exception:
        return None


def quotes(tickers):
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(quote_one, tickers) if r]
    return pd.DataFrame(rows, columns=["sym", "name", "px", "chg", "vol", "avg", "mcap"])


def scan_screener():
    from yfinance import EquityQuery
    q = EquityQuery("and", [EquityQuery("is-in", ["exchange", "NMS", "NYQ", "ASE", "NCM", "NGM"]),
                            EquityQuery("gt", ["dayvolume", MIN_DAYVOL]), EquityQuery("gt", ["intradayprice", MIN_PRICE])])
    rows = []
    for off in range(0, 3000, 250):
        qs = (retry(lambda: yf.screen(q, offset=off, size=250, sortField="dayvolume", sortAsc=False)) or {}).get("quotes", [])
        rows += qs
        if len(qs) < 250:
            break
    df = pd.DataFrame([dict(sym=x.get("symbol"), name=x.get("shortName") or x.get("symbol"), px=x.get("regularMarketPrice"),
                            chg=x.get("regularMarketChangePercent"), vol=x.get("regularMarketVolume"),
                            avg=x.get("averageDailyVolume3Month"), mcap=x.get("marketCap")) for x in rows])
    if df.empty:
        raise RuntimeError("screener vacío")
    return df


def sp_symbols():
    out = []
    for u in ("S%26P_500", "S%26P_400", "S%26P_600"):
        try:
            r = requests.get(f"https://en.wikipedia.org/wiki/List_of_{u}_companies", headers=UA, timeout=20); r.raise_for_status()
            for t in pd.read_html(StringIO(r.text)):
                c = [x for x in t.columns if str(x).lower() in ("symbol", "ticker symbol", "ticker")]
                if c:
                    out += t[c[0]].astype(str).str.replace(".", "-", regex=False).tolist(); break
        except Exception as e:
            logging.warning("Lista %s: %s", u, type(e).__name__)
    return sorted(set(out))


def scan_fallback():
    syms, rows = sp_symbols(), []
    if not syms:
        raise RuntimeError("sin lista de respaldo")
    for i in range(0, len(syms), 100):
        part = syms[i:i + 100]
        try:
            d = retry(lambda: yf.download(part, period="3mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True), 2)
        except Exception:
            continue
        for t in part:
            try:
                x = d[t].dropna(subset=["Close"]); v = x["Volume"]
                rows.append(dict(sym=t, name=t, px=x.Close.iloc[-1], chg=(x.Close.iloc[-1] / x.Close.iloc[-2] - 1) * 100,
                                 vol=v.iloc[-1], avg=v.iloc[-61:-1].mean(), mcap=float("nan")))
            except Exception:
                pass
    return pd.DataFrame(rows)


def scan_universe():
    for fn, label in ((scan_screener, "screener Yahoo"), (scan_fallback, "S&P 1500 (respaldo)")):
        try:
            df = fn()
            if len(df) > 50:
                return df, label
        except Exception as e:
            logging.warning("%s falló: %s", label, type(e).__name__)
    raise RuntimeError("ninguna fuente de universo disponible")


def add_rv(df, filt=True):
    df = df.copy()
    for c in ("px", "chg", "vol", "avg", "mcap"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["chg"] = df["chg"].fillna(0.0)
    if filt:
        df = df[(df.avg >= MIN_AVGVOL) & (df.px >= MIN_PRICE) & (df.vol > 0)]
    df["rv"] = df.vol / (df.avg * session_fraction())
    return df.drop_duplicates("sym").reset_index(drop=True)


tier = lambda rv: "RED" if rv >= RED_T else "YELLOW" if rv >= YEL_T else "GREEN"


def pick_radar(U, banned, n, seed):
    c = U[(U.rv >= RED_T) & (~U.sym.isin(banned))]
    if c.empty or n <= 0:
        return []
    rng, m = random.Random(seed), c.mcap.fillna(1e9)  # 1/3 micro, 1/3 small-mid, 1/3 large (+ADR/especulativas incluidas)
    pick, per = [], max(1, n // 3)
    for b in (c[m < 3e8], c[(m >= 3e8) & (m < 1e10)], c[m >= 1e10]):
        pick += rng.sample(list(b.sym), min(per, len(b)))
    rest = [s for s in c.sym if s not in pick]; rng.shuffle(rest)
    return (pick + rest)[:n]


def rsi5(c):
    d = c.diff(); g, l = d.clip(lower=0).rolling(5).mean(), (-d.clip(upper=0)).rolling(5).mean()
    return float((100 - 100 / (1 + g / l.replace(0, np.nan))).iloc[-1])


def histories(tickers):
    out = {}
    try:
        d = retry(lambda: yf.download(tickers, period="4mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True), 2)
    except Exception:
        return out
    for t in tickers:
        try:
            x = d[t].dropna(subset=["Close"])
            if len(x) >= 25:
                out[t] = x
        except Exception:
            pass
    return out


def make_rec(r, grp, H):
    x = H.get(r.sym)
    cl = [round(float(v), 2) for v in x.Close.tail(60)] if x is not None else []
    em = [round(float(v), 2) for v in x.Close.ewm(span=20, adjust=False).mean().tail(60)] if x is not None else []
    return dict(s=r.sym, g=grp, l=tier(r.rv), p=round(num(r.px), 2), c=round(num(r.chg), 2), r=round(num(rsi5(x.Close)) if x is not None else 0),
                v=round((cl[-1] / em[-1] - 1) * 100, 1) if cl and em[-1] else 0, n=0, a=round(num(r.rv), 2), cmf=round(num(r.rv), 2),
                rs=round(num(r.chg), 2), dv=num(r.px * r.vol), cl=cl, em=em)


def cap_tag(m): return "" if not np.isfinite(m) else "micro" if m < 3e8 else "small/mid" if m < 1e10 else "large"
def fmt(r): return f"{r.sym} {r.rv:.1f}x {r.chg:+.1f}% {'▲' if r.chg > 0 else '▼' if r.chg < 0 else '•'}"


# ---------- noticias en español ----------
def gnews(q, hours=6):
    url = f"https://news.google.com/rss/search?q={quote_plus(q + f' when:{hours}h')}&hl=es-419&gl=PE&ceid=PE:es-419"
    r = retry(lambda: requests.get(url, headers=UA, timeout=15)); r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        try:
            title = (it.findtext("title") or "").strip(); src = (it.findtext("source") or "").strip()
            if src and title.endswith(" - " + src):
                title = title[:-len(src) - 3]
            out.append(dict(title=title, src=src, link=it.findtext("link") or "", pub=parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)))
        except Exception:
            pass
    return out


def impact(title, port, direct=None):
    low, aff, themes = title.lower(), set(), []
    if direct:
        aff.add(direct)
    for pat, (lab, tks) in THEMES.items():
        if re.search(pat, low):
            themes.append(lab); aff |= set(tks.split()) & port
    for t, a in ALIAS.items():  # menciones por nombre o ticker, con límites de palabra (evita falsos positivos)
        if t in port:
            names = [a.lower()] + ([a.split()[0].lower()] if len(a.split()[0]) >= 5 else [])
            if any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in names) or re.search(r"\b" + t + r"\b", title):
                aff.add(t)
    return sorted(aff), themes


def tone(title):
    low = title.lower(); p, n = sum(w in low for w in POS), sum(w in low for w in NEG)
    return "🟢" if p > n else "🔴" if n > p else "⚪"


def scan_news(port, st, manual):
    pset = set(port)
    qs = [(t, f'"{ALIAS[t]}"' if t in ALIAS else f"{t} acciones") for t in port if t not in ETFS] + [(None, q) for q in GENERAL]
    def fetch(x):
        try:
            return x[0], gnews(x[1]), None
        except Exception as e:
            return x[0], [], type(e).__name__
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(fetch, qs))
    items, seen = {}, set(st.get("_NEWS", []))
    first = "_NEWS" not in st
    if res and all(e for _, _, e in res):
        raise RuntimeError("todas las consultas de noticias fallaron")
    for direct, its, _ in res:
        for it in its:
            h = hashlib.md5(re.sub(r"\W+", "", it["title"].lower()).encode()).hexdigest()[:12]
            if h not in items:
                aff, th = impact(it["title"], pset, direct)
                if aff or th:
                    items[h] = dict(it, aff=aff, th=th)
    new = {h: v for h, v in items.items() if h not in seen}
    st["_NEWS"] = (list(seen) + list(new))[-1500:]
    pick = list((items if manual else new).items()) if not (first and not manual) else []
    pick = sorted(pick, key=lambda kv: (not kv[1]["aff"], -kv[1]["pub"].timestamp()))[:8]
    if not pick:
        return 0
    now, lines = datetime.now(timezone.utc), [f"📰 NOTICIAS · {lima_now():%H:%M} (hora Lima)"]
    for i, (_, v) in enumerate(pick, 1):
        mins = int((now - v["pub"]).total_seconds() / 60)
        age = f"hace {mins} min" if mins < 90 else f"hace {mins // 60} h"
        lines.append(f"{i}. {tone(v['title'])} {v['title']} ({v['src']}, {age})")
        mine = [t for t in v["aff"] if t in pset]
        lines.append("   ↳ " + (f"Afecta a tu cartera: {', '.join(mine)}" if mine else "Mercado general") + (f" · Tema: {', '.join(v['th'])}" if v["th"] else ""))
        lines.append("   " + v["link"])
    tg("\n".join(lines))
    return len(pick)


# ---------- IAIT (diario) ----------
def run_iait():
    eng = IAITOptimizerV2(window=60)
    m = MarketDataFetcher().get_latest_market_metrics(eng)
    res = eng.evaluate(m); lvl = res["level"]
    if lvl == "NEUTRAL" and m.price < m.ema20 and m.vix_ts > 1.0:
        lvl = "RED"
    hz = {"YELLOW": "Horizonte: ~5-7 días hábiles hasta un posible verde.", "PRE_GREEN": "IAIT alto: espera confirmación de precio y volumen.",
          "GREEN": "Ventana de entrada abierta: tramos 25% / 50% / 25%.", "RED": "Estrés sin absorción institucional: sin compras anticipadas."}
    txt = hz.get(lvl) or ("Sin corrección previa: el IAIT no aplica todavía." if not res["stress_gate"] else "Corrección en curso, aún sin señal.")
    names = {"dix": "DIX", "gex": "GEX", "vix_ts": "VIX/VIX3M", "hy_spread_change": "Spread HY 5d"}
    mkt = dict(score=res["score"], lvl=lvl, gate=bool(res["stress_gate"]), txt=txt,
               vars=[dict(n=names[k], w=round(eng.weights[k] * 100), s=v["score"], z=v["z_score"]) for k, v in res["breakdown"].items()])
    hist = [{k: (None if v is None else (round(v, 3) if isinstance(v, float) else v)) for k, v in r.items()} for r in eng.hist_rows[-60:]]
    hist.append(dict(d="hoy", dix=round(m.dix, 2), ts=round(m.vix_ts, 3), iait=res["score"]))
    return dict(mkt=mkt, h=hist)


# ---------- orquestación ----------
def safe(name, fn, st):
    f = st.setdefault("_FAIL", {})
    try:
        r = fn(); f[name] = 0; return r
    except Exception as e:
        f[name] = f.get(name, 0) + 1
        logging.error("%s falló (%s): %s", name, type(e).__name__, str(e)[:150])
        if f[name] == 3:
            tg(f"⚠️ La fuente «{name}» falla hace 3 corridas seguidas ({type(e).__name__}). El resto del sistema sigue activo.")
        return None


def main():
    now, st = lima_now(), load_state()
    manual = os.getenv("GITHUB_EVENT_NAME", "manual") in ("workflow_dispatch", "manual")
    port, extra, excl = env_list("PORTFOLIO_TICKERS"), env_list("EXTRA_TICKERS"), set(env_list("EXCLUDE_TICKERS"))
    if not port:
        tg("⚠️ Falta el secret PORTFOLIO_TICKERS (tus tickers separados por espacio). Sin él el sistema no puede monitorear tu cartera."); return
    last = st.get("_LAST_OK")
    if last:
        gap = (now - datetime.fromisoformat(last)).total_seconds() / 60
        if gap > 90:
            tg(f"⚠️ Retraso: pasaron {gap:.0f} min sin corridas (GitHub puede demorar o pausar tareas programadas). Sistema activo de nuevo.")
    slot, today = now.strftime("%Y-%m-%d-%H"), now.strftime("%Y-%m-%d")
    in_window = now.weekday() < 5 and 8 <= now.hour <= 21
    hourly = manual or (in_window and st.get("_SLOT") != slot)
    daily = manual or (now.hour * 60 + now.minute >= 570 and st.get("_DAILY") != today)

    safe("noticias", lambda: scan_news(port, st, manual), st)

    vol = None
    if in_window or hourly or daily:
        def volume_stage():
            raw, label = scan_universe()
            U = add_rv(raw)
            P = add_rv(quotes(port + extra), filt=False)
            monitored = set(port) | set(extra)
            seed = int(hashlib.md5(slot.encode()).hexdigest()[:8], 16)
            radar = pick_radar(U, monitored | excl, TOTAL - len(monitored), seed)
            R = U[U.sym.isin(radar)].sort_values("rv", ascending=False)
            allm = pd.concat([P, R])
            H = histories(list(allm.sym))
            recs = [make_rec(r, "P" if r.sym in port else "F", H) for r in P.itertuples()] + [make_rec(r, "R", H) for r in R.itertuples()]
            return dict(U=U, P=P, R=R, recs=recs, label=label)
        vol = safe("volumen", volume_stage, st)

    if vol:
        U, P, R = vol["U"], vol["P"], vol["R"]
        prev = set(st.get("_RED", [])); ids = {hid(s): s for s in U.sym}
        nowred = {hid(r.sym) for r in U.itertuples() if r.rv >= RED_T or (hid(r.sym) in prev and r.rv >= EXIT_T)}
        entering = U[U.sym.map(hid).isin(nowred - prev)]
        seeded = "_RED" in st
        if in_window and seeded and not entering.empty:
            e = entering.assign(p=entering.sym.isin(port + extra)).sort_values(["p", "rv"], ascending=False)
            lines = [f"🚨 ENTRADA A ROJO (>{RED_T}x volumen) · {now:%H:%M} (hora Lima)", session_text()]
            for r in e.head(EVENT_ROWS).itertuples():
                lines.append(("⭐ " if r.p else "• ") + fmt(r) + f" ${r.px:.2f} {cap_tag(r.mcap)}".rstrip())
            if len(e) > EVENT_ROWS:
                lines.append(f"(+{len(e) - EVENT_ROWS} más; ver dashboard en el reporte horario)")
            for r in e[~e.p].head(3).itertuples():
                try:
                    n = gnews(f"{r.sym} acciones", 24)
                    if n:
                        lines.append(f"📰 {r.sym}: {n[0]['title']} ({n[0]['src']})")
                except Exception:
                    pass
            tg("\n".join(lines))
        st["_RED"] = sorted(nowred)

        mkt = st.get("_MKT") or dict(mkt=dict(score=None, lvl="NEUTRAL", gate=None, vars=[], txt="IAIT aún no calculado (se calcula una vez al día)."), h=[])
        if daily:
            m2 = safe("IAIT", run_iait, st)
            if m2:
                mkt = m2; st["_MKT"] = m2
        out = os.path.join(BASE, "iait_dashboard.html")
        note = f"universo: {len(U)} acciones · fuente: {vol['label']} · {'sesión abierta' if session_open() else 'datos del último cierre'}"
        tpl = open(os.path.join(BASE, "dashboard_template.html"), encoding="utf-8").read()
        open(out, "w", encoding="utf-8").write(tpl.replace("__DATA__", json.dumps(dict(mkt=mkt["mkt"], h=mkt["h"], t=vol["recs"], stamp=f"{now:%Y-%m-%d %H:%M} (hora Lima)", note=note), ensure_ascii=False)))
        pr = P[P.rv >= RED_T].sort_values("rv", ascending=False)
        if hourly:
            top = U[~U.sym.isin(port + extra)].sort_values("rv", ascending=False).head(EVENT_ROWS)
            nred = int((U.rv >= RED_T).sum())
            L = [f"⏰ REPORTE HORARIO · {DIAS[now.weekday()]} {now:%d/%m %H:%M} (hora Lima)", session_text(), f"Universo analizado: {len(U)} acciones de NY ({vol['label']})",
                 "🔴 Tu cartera >%.1fx (%d): " % (RED_T, len(pr)) + (", ".join(fmt(r) for r in pr.itertuples()) if len(pr) else "ninguna"),
                 f"🔴 Mercado NY: {nred} acciones >{RED_T}x. Mayores 15:"]
            L += [f"• {fmt(r)} ${r.px:.2f} {cap_tag(r.mcap)}".rstrip() for r in top.itertuples()]
            L.append(f"🎲 Radar ({len(R)} aleatorias >{RED_T}x): " + ", ".join(f"{r.sym} {r.rv:.1f}x" for r in R.itertuples()))
            tg("\n".join(L), out)
            st["_SLOT"] = slot
        if daily:
            mk = mkt["mkt"]
            tg(f"📊 REPORTE DIARIO · {DIAS[now.weekday()]} {now:%d/%m} 9:30 (hora Lima)\nMercado IAIT: {LABEL.get(mk['lvl'], mk['lvl'])} · {mk['score'] if mk['score'] is not None else 'N/D'}/100\n{mk['txt']}\n"
               f"Tu cartera con volumen >{RED_T}x: " + (", ".join(pr.sym) if len(pr) else "ninguna") + "\n✅ Sistema activo", out)
            st["_DAILY"] = today
    st["_LAST_OK"] = now.isoformat()
    save_state(st)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error("Falla general: %s\n%s", type(e).__name__, traceback.format_exc()[-800:])
        s = load_state()
        if s.get("_ERR_AT") != lima_now().strftime("%Y-%m-%d-%H"):
            tg(f"🛑 Falla en el sistema IAIT ({type(e).__name__}). Revisa Actions en GitHub.")
            s["_ERR_AT"] = lima_now().strftime("%Y-%m-%d-%H"); save_state(s)
        sys.exit(1)
