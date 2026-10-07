import os
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. CONFIGURACIÓN DE CREDENCIALES
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    """Envía el reporte formateado a Telegram asegurando manejo de errores HTTP."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error crítico: Credenciales de Telegram no configuradas en GitHub Secrets.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Respuesta Telegram API: {response.status_code}")
    except Exception as e:
        print(f"Error al despachar mensaje a Telegram: {e}")

# 2. UNIVERSO DE ACTIVOS DE ALTA LIQUIDEZ Y COMPONENTES CLAVE
universo = [
    'MU', 'CRDO', 'BE', 'IBM', 'RKLB', 'GLD', 'RTX', 'KLAC', 'SCHD',
    'FLEX', 'AMZN', 'VTV', 'LLY', 'VRT', 'CRWD', 'QQQM', 'GOOGL',
    'VOO', 'NVDA', 'VST', 'MSFT', 'AVGO', 'CEG', 'ALAB', 'TSM', 'MELI',
    'AAPL', 'META', 'TSLA', 'NFLX', 'AMD', 'INTC', 'JPM', 'XOM', 'CVX'
]

# 3. MÓDULO DE TRADUCCIÓN AUTOMÁTICA AL ESPAÑOL
def traducir_texto(texto):
    """Traduce de forma gratuita y rápida un titular al español usando el servicio público de MyMemory."""
    if not texto or "Sin catalizador" in texto:
        return texto
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {'q': texto, 'langpair': 'en|es'}
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            traduccion = data.get('responseData', {}).get('translatedText')
            if traduccion:
                return traduccion
    except Exception:
        pass
    return texto  # Si falla por red, devuelve el original en inglés como respaldo

# 4. MOTOR CUALITATIVO DE NOTICIAS CON DOBLE REDUNDANCIA
def obtener_noticia_relevante(ticker_symbol):
    """Busca el catalizador del día mediante feeds RSS públicos y traduce el resultado."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    titulo_encontrado = None

    # Intento 1: Yahoo Finance RSS
    try:
        url_yahoo = f"https://finance.yahoo.com/rss/headline?s={ticker_symbol}"
        resp = requests.get(url_yahoo, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'xml')
            item = soup.find('item')
            if item and item.title:
                titulo = item.title.text.strip()
                if titulo:
                    titulo_encontrado = titulo
    except Exception:
        pass

    # Intento 2: Google News RSS (Respaldo)
    if not titulo_encontrado:
        try:
            url_google = f"https://news.google.com/rss/search?q={ticker_symbol}+stock&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url_google, headers=headers, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'xml')
                item = soup.find('item')
                if item and item.title:
                    titulo = item.title.text.strip()
                    if titulo:
                        titulo_encontrado = titulo
        except Exception:
            pass

    if titulo_encontrado:
        # Traducimos el titular al español antes de retornarlo
        return traducir_texto(titulo_encontrado)

    return "Sin catalizador reciente detectado en feeds públicos"

# 5. MOTOR CUANTITATIVO DE BARRIDO DE MERCADO
def barrido_mercado_global():
    resultados = []
    print(f"Iniciando auditoría sobre un universo de {len(universo)} activos...")

    for ticker in universo:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="90d")
            if hist is None or len(hist) < 65:
                continue

            volumen_actual = hist['Volume'].iloc[-1]
            ma_volumen_65 = hist['Volume'].iloc[-65:-1].mean()

            if ma_volumen_65 > 0:
                ratio = volumen_actual / ma_volumen_65
                precio_cierre = hist['Close'].iloc[-1]

                if ratio >= 1.2:
                    noticia = obtener_noticia_relevante(ticker)
                    resultados.append({
                        'ticker': ticker,
                        'precio': precio_cierre,
                        'ratio': ratio,
                        'noticia': noticia
                    })
        except Exception as e:
            print(f"Advertencia procesando ticker {ticker}: {e}")
            continue

    return resultados

# 6. ORQUESTADOR PRINCIPAL
def main():
    peru_tz = ZoneInfo("America/Lima")
    ahora_peru = datetime.now(peru_tz).strftime("%Y-%m-%d %H:%M:%S")

    anomalias = barrido_mercado_global()

    if anomalias:
        anomalias = sorted(anomalias, key=lambda x: x['ratio'], reverse=True)
        
        mensaje = f"🚨 *ALERTA HÍBRIDA AUTÓNOMA (>1.2x)* 🚨\n"
        mensaje += f"⏱ Hora Lima: {ahora_peru}\n\n"

        for item in anomalias:
            t = item['ticker']
            p = item['precio']
            r = item['ratio']
            noticia = item['noticia']

            mensaje += f"🔴 ⭐ *{t}* | ${p:.2f} | Vol 3M: {r:.2f}x\n"
            mensaje += f"   📰 *Catalizador:* _{noticia}_\n\n"
    else:
        mensaje = f"🔍 *Escaneo Híbrido Completado*\n⏱ Hora Lima: {ahora_peru}\nNo se registraron anomalías de volumen institucional (>1.2x) en este ciclo."

    enviar_telegram(mensaje)

if __name__ == "__main__":
    main()
