import os
import random
import requests
from io import StringIO
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

portafolio_base = [
    'MU', 'CRDO', 'BE', 'IBM', 'RKLB', 'GLD', 'RTX', 'KLAC', 'SCHD', 
    'FLEX', 'AMZN', 'VTV', 'LLY', 'VRT', 'CRWD', 'QQQM', 'GOOGL', 
    'VOO', 'NVDA', 'VST', 'MSFT', 'AVGO', 'CEG', 'ALAB', 'TSM', 'MELI'
]

def barrido_mercado_global():
    tickers_encontrados = set()
    urls = [
        'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        'https://en.wikipedia.org/wiki/List_of_NASDAQ-100_components'
    ]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    for u in urls:
        try:
            r = requests.get(u, headers=headers, timeout=8)
            if r.status_code == 200:
                df = pd.read_html(StringIO(r.text))[0]
                col = 'Symbol' if 'Symbol' in df.columns else ('Ticker' if 'Ticker' in df.columns else df.columns[0])
                for s in df[col].astype(str):
                    clean_s = s.split()[0].replace('.', '-').upper()
                    if clean_s.isalpha() and len(clean_s) <= 5:
                        tickers_encontrados.add(clean_s)
        except Exception:
            continue
            
    try:
        r2 = requests.get('https://query1.finance.yahoo.com/v1/finance/screener/predefined/generated_s_most_actives', headers=headers, timeout=5)
        if r2.status_code == 200:
            data_json = r2.json().get('finance', {}).get('result', [{}])
            if data_json and len(data_json) > 0:
                quotes = data_json[0].get('quotes', [])
                for q in quotes:
                    sym = q.get('symbol')
                    if sym and '.' not in sym and sym.isalpha() and len(sym) <= 5:
                        tickers_encontrados.add(sym.upper())
    except Exception:
        pass

    return list(tickers_encontrados)

universo_global = barrido_mercado_global()
candidatos_externos = [s for s in universo_global if s not in portafolio_base]
random.shuffle(candidatos_externos)

cupo_autonomo = candidatos_externos[:max(0, 50 - len(portafolio_base))]
tickers_a_probar = list(set(portafolio_base + cupo_autonomo))

activos_detectados = []

for t in tickers_a_probar:
    try:
        df = yf.download(t, period='4mo', interval='1d', progress=False)
        if not df.empty and 'Close' in df.columns and 'Volume' in df.columns:
            if isinstance(df.columns, pd.MultiIndex): 
                df.columns = df.columns.get_level_values(0)
            
            df = df.dropna(subset=['Close', 'Volume']).sort_index(ascending=False)
            
            if len(df) >= 66:
                cierre = float(df['Close'].iloc[0])
                v_act = float(df['Volume'].iloc[0])
                v_prom = float(df['Volume'].iloc[1:66].mean())
                
                vr = (v_act / v_prom) if v_prom > 0 else 1.0
                
                if vr > 1.2:
                    es_base = '⭐ ' if t in portafolio_base else '   '
                    activos_detectados.append({
                        'ticker': f'{es_base}{t}',
                        'precio': round(cierre, 2),
                        'vr': round(vr, 2)
                    })
    except Exception:
        pass

hora_peru = datetime.now(ZoneInfo('America/Lima')).strftime('%H:%M:%S')

if activos_detectados:
    activos_detectados = sorted(activos_detectados, key=lambda x: x['vr'], reverse=True)
    msg = f'🚨 *ALERTA GLOBAL AUTÓNOMA (>1.2x)* 🚨\n⏰ Hora Lima: {hora_peru}\n\n'
    for item in activos_detectados:
        msg += f"🔴 `{item['ticker']}` | ${item['precio']} | Vol 3M: *{item['vr']}x*\n"
else:
    msg = f'📊 *IAIT MONITOR GLOBAL* 📊\n⏰ Hora Lima: {hora_peru}\n\nSin activos cumpliendo el umbral rojo (>1.2x) en este ciclo.'

requests.post('https://api.telegram.org/bot8929263014:AAG5oHs5tp6znS5EqKHejlV62z6cEgGo12k/sendMessage', json={'chat_id': '8596315311', 'text': msg, 'parse_mode': 'Markdown'})
