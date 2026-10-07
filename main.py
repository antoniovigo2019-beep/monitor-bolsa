import os
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

# Configuración de Telegram (lee los secretos de GitHub Actions)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Credenciales de Telegram no configuradas en GitHub Secrets.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Respuesta Telegram API: {response.status_code}")
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

# Universo robusto de activos de alta liquidez y componentes clave
universo = [
    'MU', 'CRDO', 'BE', 'IBM', 'RKLB', 'GLD', 'RTX', 'KLAC', 'SCHD',
    'FLEX', 'AMZN', 'VTV', 'LLY', 'VRT', 'CRWD', 'QQQM', 'GOOGL',
    'VOO', 'NVDA', 'VST', 'MSFT', 'AVGO', 'CEG', 'ALAB', 'TSM', 'MELI',
    'AAPL', 'META', 'TSLA', 'NFLX', 'AMD', 'INTC', 'JPM', 'XOM', 'CVX'
]

def obtener_noticia_relevante(ticker_symbol):
    """Consulta mejorada para extraer el último titular disponible de la acción"""
    try:
        tk = yf.Ticker(ticker_symbol)
        noticias = getattr(tk, 'news', None)
        if not noticias:
            return None
        
        ultima = noticias[0]
        titulo = ultima.get('title') or ultima.get('content', {}).get('title')
        if not titulo:
            return None
        return titulo
    except Exception:
        return None

def barrido_mercado_global():
    resultados = []
    print(f"Analizando un universo de {len(universo)} activos...")

    for ticker in universo:
        try:
            tk = yf.Ticker(ticker)
            # Usamos '90d' exactos para cumplir con los filtros de yfinance
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
            print(f"Error procesando {ticker}: {e}")
            continue

    return resultados

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
            if noticia:
                mensaje += f"   📰 *Catalizador:* _{noticia}_\n"
            mensaje += "\n"
    else:
        mensaje = f"🔍 *Escaneo Híbrido Completado*\n⏱ Hora Lima: {ahora_peru}\nNo se registraron anomalías de volumen institucional (>1.2x) en este ciclo."

    enviar_telegram(mensaje)

if __name__ == "__main__":
    main()
