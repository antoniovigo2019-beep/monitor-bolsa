import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

# Configuración de Telegram (lee los secretos configurados en GitHub Actions)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Credenciales de Telegram no configuradas.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

portafolio_base = [
    'MU', 'CRDO', 'BE', 'IBM', 'RKLB', 'GLD', 'RTX', 'KLAC', 'SCHD',
    'FLEX', 'AMZN', 'VTV', 'LLY', 'VRT', 'CRWD', 'QQQM', 'GOOGL',
    'VOO', 'NVDA', 'VST', 'MSFT', 'AVGO', 'CEG', 'ALAB', 'TSM', 'MELI'
]

def obtener_noticia_relevante(ticker_symbol):
    """Consulta los últimos titulares de la acción para detectar catalizadores cualitativos"""
    try:
        tk = yf.Ticker(ticker_symbol)
        noticias = tk.news
        if not noticias:
            return None
        # Retorna el título de la noticia más reciente
        ultima = noticias[0]
        # Dependiendo de la estructura de yfinance, el título puede estar en 'title' o dentro de 'content'
        titulo = ultima.get('title') or ultima.get('content', {}).get('title')
        return titulo
    except Exception as e:
        return None

def barrido_mercado_global():
    tickers_encontrados = set()
    urls = [
        'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        'https://en.wikipedia.org/wiki/List_of_NASDAQ-100_components'
    ]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for u in urls:
        try:
            df_list = pd.read_html(u, storage_options={'User-Agent': 'Mozilla/5.0'})
            for df in df_list:
                for col in ['Symbol', 'Ticker']:
                    if col in df.columns:
                        symbols = df[col].astype(str).str.replace('.', '-', regex=False).tolist()
                        tickers_encontrados.update(symbols)
                        break
        except Exception as e:
            print(f"Error al leer Wikipedia ({u}): {e}")

    # Combinar Wikipedia con tu portafolio base personalizado
    universo = sorted(list(tickers_encontrados.union(set(portafolio_base))))
    
    resultados = []
    print(f"Analizando un universo de {len(universo)} activos...")

    for ticker in universo:
        try:
            tk = yf.Ticker(ticker)
            # Descargamos los últimos ~70 días para calcular la media móvil de 65 ruedas
            hist = tk.history(period="3m")
            if hist is None or len(hist) < 65:
                continue

            volumen_actual = hist['Volume'].iloc[-1]
            ma_volumen_65 = hist['Volume'].iloc[-65:-1].mean()

            if ma_volumen_65 > 0:
                ratio = volumen_actual / ma_volumen_65
                precio_cierre = hist['Close'].iloc[-1]

                # Filtro de anomalía de volumen institucional (> 1.2x)
                if ratio >= 1.2:
                    noticia = obtener_noticia_relevante(ticker)
                    resultados.append({
                        'ticker': ticker,
                        'precio': precio_cierre,
                        'ratio': ratio,
                        'noticia': noticia
                    })
        except Exception as e:
            # Ignoramos errores puntuales de tickers deslistados o sin datos
            continue

    return resultados

def main():
    peru_tz = ZoneInfo("America/Lima")
    ahora_peru = datetime.now(peru_tz).strftime("%Y-%m-%d %H:%M:%S")

    anomalias = barrido_mercado_global()

    if anomalias:
        # Ordenar de mayor a menor ratio de volumen
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
