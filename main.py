import os
import random
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. CONFIGURACIÓN DE CREDENCIALES
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    """Envía el reporte estructurado a Telegram con control de errores."""
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

# 2. TU PORTAFOLIO OFICIAL (Base obligatoria de escaneo)
portafolio_usuario = [
    'CEG', 'ALAB', 'CRDO', 'BE', 'KLAC', 'GLD', 'MU', 'VST', 'VRT', 
    'RKLB', 'AVGO', 'GOOGL', 'TSM', 'QQQM', 'FLEX', 'VTV', 'MELI', 
    'SCHD', 'AMZN', 'VOO', 'LLY', 'NVDA', 'MSFT', 'CRWD'
]

# Pool complementario de alta liquidez para completar dinámicamente hasta 50 activos
pool_complementario = [
    'AAPL', 'META', 'TSLA', 'NFLX', 'AMD', 'INTC', 'JPM', 'XOM', 'CVX',
    'IBM', 'RTX', 'TQQQ', 'ARKK', 'SQ', 'COIN', 'SHOP', 'BA', 'DIS',
    'PYPL', 'ADBE', 'CRM', 'QCOM', 'TXN', 'INTU', 'AMAT', 'LMT', 'GE'
]

def obtener_universo_operativo():
    """Combina estrictamente tu portafolio con una selección aleatoria para completar 50 activos."""
    # Aseguramos que no se repitan elementos
    extras_necesarios = max(0, 50 - len(portafolio_usuario))
    seleccion_dinamica = random.sample(pool_complementario, min(extras_necesarios, len(pool_complementario)))
    universo_total = list(set(portafolio_usuario + seleccion_dinamica))
    return universo_total

# 3. MÓDULO DE TRADUCCIÓN AUTOMÁTICA AL ESPAÑOL
def traducir_texto(texto):
    """Traduce titulares al español mediante la API pública de MyMemory."""
    if not texto:
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
    return texto

# 4. CAPA DE CATALIZADORES ESTRATÉGICOS Y SECTORIALES
def obtener_catalizadores_estrategicos():
    """Busca eventos de alto impacto, M&A, contratos y macroeconomía regional."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    queries = [
        "merger acquisition stock deal buyout",
        "FDA approval biotech clinical trial stock",
        "energy contract AI data center stock",
        "Latin America market economy stock"
    ]
    catalizadores = []
    
    for q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'xml')
                items = soup.find_all('item', limit=1)
                for item in items:
                    if item.title:
                        titulo = item.title.text.strip()
                        traducido = traducir_texto(titulo)
                        if traducido and traducido not in catalizadores:
                            catalizadores.append(traducido)
        except Exception:
            continue
            
    return catalizadores[:3]

# 5. CAPA CUANTITATIVA DE BARRIDO DE MERCADO
def barrido_mercado_global(universo):
    resultados = []
    print(f"Iniciando auditoría cuantitativa sobre un universo combinado de {len(universo)} activos...")

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
                    es_portafolio = "⭐ (Tu Portafolio)" if ticker in portafolio_usuario else "⚡ (Dinámico)"
                    resultados.append({
                        'ticker': ticker,
                        'precio': precio_cierre,
                        'ratio': ratio,
                        'etiqueta': es_portafolio
                    })
        except Exception as e:
            print(f"Advertencia procesando ticker {ticker}: {e}")
            continue

    return resultados

# 6. ORQUESTADOR PRINCIPAL DEL REPORTE HÍBRIDO
def main():
    peru_tz = ZoneInfo("America/Lima")
    ahora_peru = datetime.now(peru_tz).strftime("%Y-%m-%d %H:%M:%S")

    universo_actual = obtener_universo_operativo()
    estrategicos = obtener_catalizadores_estrategicos()
    anomalias = barrido_mercado_global(universo_actual)

    mensaje = f"🚨 *REPORTE DE INTELIGENCIA DE MERCADO* 🚨\n"
    mensaje += f"⏱ Hora Lima: {ahora_peru}\n\n"

    # Sección 1: Catalizadores Estratégicos y Sectoriales
    mensaje += "🎯 *Catalizadores Estratégicos y Sectoriales:*\n"
    if estrategicos:
        for noticia in estrategicos:
            mensaje += f" • 📰 _{noticia}_\n"
    else:
        mensaje += " • Sin eventos corporativos extraordinarios en este ciclo.\n"
    mensaje += "\n"

    # Sección 2: Anomalías Cuantitativas (>1.2x)
    mensaje += "📊 *Anomalías de Volumen Institucional (>1.2x):*\n"
    if anomalias:
        anomalias = sorted(anomalias, key=lambda x: x['ratio'], reverse=True)
        for item in anomalias:
            t = item['ticker']
            p = item['precio']
            r = item['ratio']
            tag = item['etiqueta']
            mensaje += f" 🔴 *{t}* {tag} | ${p:.2f} | Vol 3M: {r:.2f}x\n"
    else:
        mensaje += " • No se registraron anomalías de volumen institucional en este ciclo.\n"

    enviar_telegram(mensaje)

if __name__ == "__main__":
    main()
