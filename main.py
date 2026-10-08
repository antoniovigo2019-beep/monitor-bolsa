import os
import random
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def traducir_texto(texto):
    if not texto:
        return texto
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {'q': texto, 'langpair': 'en|es'}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            return res.json().get('responseData', {}).get('translatedText', texto)
    except Exception:
        pass
    return texto

def obtener_catalizadores_macro():
    headers = {'User-Agent': 'Mozilla/5.0'}
    queries = [
        "merger acquisition stock deal buyout",
        "FDA approval biotech clinical trial stock",
        "energy contract AI data center stock",
        "global market economy stock catalyst"
    ]
    catalizadores = []
    for q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'xml')
                item = soup.find('item')
                if item and item.title:
                    titulo = item.title.text.strip()
                    traducido = traducir_texto(titulo)
                    if traducido and traducido not in catalizadores:
                        catalizadores.append(traducido)
        except Exception:
            pass
    return catalizadores[:3]

def generar_universo_libre():
    pool_global = [
        'PENG', 'CEG', 'ALAB', 'CRDO', 'BE', 'KLAC', 'GLD', 'MU', 'VST', 'VRT', 
        'RKLB', 'AVGO', 'GOOGL', 'TSM', 'QQQM', 'FLEX', 'VTV', 'MELI', 'SCHD', 
        'AMZN', 'VOO', 'LLY', 'NVDA', 'MSFT', 'CRWD', 'AAPL', 'META', 'TSLA', 
        'NFLX', 'AMD', 'INTC', 'JPM', 'XOM', 'CVX', 'IBM', 'RTX', 'TQQQ', 'ARKK', 
        'SQ', 'COIN', 'SHOP', 'BA', 'DIS', 'PYPL', 'ADBE', 'CRM', 'QCOM', 'TXN', 
        'INTU', 'AMAT', 'LMT', 'GE', 'PLTR', 'MRVL', 'ARM', 'SMCI', 'ENPH', 'FSLR', 
        'CELH', 'HOOD', 'RDDT', 'PFE', 'JNJ', 'XPEV', 'NIO', 'BABA', 'PDD', 'VALE', 'PBR'
    ]
    return random.sample(pool_global, min(50, len(pool_global)))

def barrido_cuantitativo():
    universo = generar_universo_libre()
    resultados = []
    print(f"Iniciando escaneo libre y autónomo sobre {len(universo)} activos...")

    for ticker in universo:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="90d")
            if hist is None or len(hist) < 65:
                continue
            
            # Limpieza de registros nulos para evitar valores nan en precios y volúmenes
            hist = hist.dropna(subset=['Close', 'Volume'])
            if len(hist) < 65:
                continue

            volumen_actual = float(hist['Volume'].iloc[-1])
            ma_volumen_65 = float(hist['Volume'].iloc[-65:-1].mean())
            
            if ma_volumen_65 > 0:
                ratio = volumen_actual / ma_volumen_65
                precio_cierre = float(hist['Close'].iloc[-1])
                
                if ratio >= 1.2 and precio_cierre > 0:
                    resultados.append({
                        'ticker': ticker,
                        'precio': precio_cierre,
                        'ratio': ratio
                    })
        except Exception as e:
            print(f"Error procesando {ticker}: {e}")
            continue
    return resultados

def main():
    peru_tz = ZoneInfo("America/Lima")
    ahora_peru = datetime.now(peru_tz).strftime("%Y-%m-%d %H:%M:%S")

    catalizadores = obtener_catalizadores_macro()
    anomalias = barrido_cuantitativo()

    mensaje = f"🚨 *REPORTE DE INTELIGENCIA DE MERCADO* 🚨\n"
    mensaje += f"⏱ Hora Lima: {ahora_peru}\n\n"

    mensaje += "🎯 *Catalizadores Macroeconómicos:*\n"
    if catalizadores:
        for cat in catalizadores:
            mensaje += f" • 📰 _{cat}\n"
    else:
        mensaje += " • Sin eventos extraordinarios en este ciclo.\n"
    mensaje += "\n"

    mensaje += "📊 *Anomalías de Volumen Institucional (>1.2x):*\n"
    if anomalias:
        anomalias = sorted(anomalias, key=lambda x: x['ratio'], reverse=True)
        for item in anomalias:
            mensaje += f" 🔴 *{item['ticker']}* | ${item['precio']:.2f} | Vol 3M: {item['ratio']:.2f}x\n"
    else:
        mensaje += " • No se registraron anomalías de volumen institucional en este ciclo.\n"

    enviar_telegram(mensaje)

if __name__ == "__main__":
    main()
