# ============================================================
# QMS QUANTUM FUTURE V5.3.2 — RETRACAO + LATENCY HUNTER
# IQ OPTION / PYDROID 3
# SOMENTE ANALISE — SEM ORDENS AUTOMATICAS — SEM MARTINGALE
# ============================================================
# IMPORTANTE:
# - Usa candles reais obtidos pela API; analisa somente candles fechados.
# - Projecoes sao estimativas tecnicas, nao garantias nem probabilidades.
# - Nao contem chamadas de compra/venda nem envia ordens.
# - Motor quantitativo adaptativo: multiplas escalas, momentum/ATR, EMAs, DIs, regime e incerteza tecnica.
# - Arquitetura inspirada em sistemas de grande escala, sem alegar bilhoes de parametros ou precisao garantida.
# ============================================================

import os
import time
import csv
import math
import logging
from datetime import datetime, timezone
from getpass import getpass

import numpy as np
import pandas as pd

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None


VERSAO = "QMS QUANTUM FUTURE V5.3.2 — RETRACAO + LATENCIA"
INTERVALO_CANDLE = 10
QUANTIDADE_CANDLES = 400
MINIMO_CANDLES = 220
INTERVALO_LOOP = 1.0
MAX_FALHAS = 12

EMA_PERIODOS = (3, 5, 8, 13, 21, 30, 50, 60, 200)
RSI_PERIODO = 14
ATR_PERIODO = 14
ADX_PERIODO = 14

SCORE_MINIMO = 5
VANTAGEM_MINIMA = 2
ADX_TENDENCIA = 20.0
ADX_LATERAL = 17.0
MAX_ESTICAMENTO_ATR = 1.50
JANELA_ROMPIMENTO = 12
JANELA_SR = 60
JANELA_ESTRUTURA_LONGA = 180
HORIZONTES_MINUTOS = (1, 2, 3, 5)
HORIZONTES_HORAS = (1, 2, 3, 4)
INTERVALO_CANDLE_HORAS = 60  # candle real de 1 minuto para contexto de varias horas
QUANTIDADE_CANDLES_HORAS = 400
MINIMO_CANDLES_HORAS = 220

CSV_PREFIXO = "qms_v532"
logging.basicConfig(
    filename="qms_v532.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def hora_local():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def formatar_hora(timestamp, utc=False):
    try:
        zona = timezone.utc if utc else datetime.now().astimezone().tzinfo
        return datetime.fromtimestamp(float(timestamp), zona).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "indisponivel"


def limpar_tela():
    os.system("cls" if os.name == "nt" else "clear")


def cor(texto, codigo):
    return f"\033[{codigo}m{texto}\033[0m"


def nome_arquivo(ativo, tipo):
    ativo_limpo = ativo.replace("-", "_").replace("/", "_")
    return f"{CSV_PREFIXO}_{ativo_limpo}_{tipo}.csv"


def salvar_csv(caminho, registro):
    existe = os.path.isfile(caminho)
    with open(caminho, "a", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(registro.keys()))
        if not existe:
            escritor.writeheader()
        escritor.writerow(registro)


def selecionar_ativo():
    while True:
        print("\nSELECIONE O ATIVO")
        print("1 - EURUSD")
        print("2 - EURUSD-OTC")
        escolha = input("Digite 1 ou 2: ").strip()
        if escolha == "1":
            return "EURUSD"
        if escolha == "2":
            return "EURUSD-OTC"
        print("Opcao invalida. Digite 1 ou 2.")


def conectar():
    if IQ_Option is None:
        raise RuntimeError("Biblioteca iqoptionapi ausente. Verifique a instalacao.")
    email = os.getenv("IQ_EMAIL") or input("E-mail IQ Option: ").strip()
    senha = os.getenv("IQ_PASSWORD") or getpass("Senha IQ Option: ")
    api = IQ_Option(email, senha)
    resultado = api.connect()
    conectado = resultado[0] if isinstance(resultado, tuple) else bool(resultado)
    if not conectado:
        raise ConnectionError("Nao foi possivel conectar a IQ Option.")
    logging.info("Conexao iniciada.")
    return api


def conexao_ativa(api):
    try:
        return bool(api.check_connect())
    except Exception:
        return False


def obter_candles(api, ativo, quantidade=QUANTIDADE_CANDLES):
    dados = api.get_candles(ativo, INTERVALO_CANDLE, quantidade, int(time.time()))
    if not dados or len(dados) < MINIMO_CANDLES:
        raise ValueError("Quantidade insuficiente de candles reais.")
    df = pd.DataFrame(dados).copy()
    obrigatorias = {"from", "open", "close", "min", "max"}
    if not obrigatorias.issubset(df.columns):
        raise ValueError("Formato inesperado recebido da API.")
    df = df.rename(columns={"from": "timestamp", "min": "low", "max": "high"})
    for coluna in ("timestamp", "open", "high", "low", "close"):
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Exige candle fechado, com pequena tolerancia natural da API.
    # CORRECAO DE LATENCIA: nao subtrair um candle extra de 10s do relogio.
    agora = time.time()
    df = df[df["timestamp"] + INTERVALO_CANDLE <= agora - 0.25].copy()
    if len(df) < MINIMO_CANDLES:
        raise ValueError("Poucos candles fechados apos a validacao.")

    if ((df["high"] < df["low"]).any()
            or (df["high"] < df[["open", "close"]].max(axis=1)).any()
            or (df["low"] > df[["open", "close"]].min(axis=1)).any()):
        raise ValueError("Dados OHLC inconsistentes.")

    diferencas = df["timestamp"].diff().dropna()
    falhas = int((diferencas > INTERVALO_CANDLE * 2).sum())
    if falhas > max(2, int(len(df) * 0.02)):
        raise ValueError("Muitos intervalos ausentes nos candles.")

    df["hora_local"] = df["timestamp"].apply(lambda x: formatar_hora(x, utc=False))
    df["hora_utc"] = df["timestamp"].apply(lambda x: formatar_hora(x, utc=True))
    return df.tail(quantidade).reset_index(drop=True)


def calcular_rsi(fechamento, periodo=14):
    delta = fechamento.diff()
    ganhos = delta.clip(lower=0)
    perdas = -delta.clip(upper=0)
    media_ganhos = ganhos.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    media_perdas = perdas.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    rs = media_ganhos / media_perdas.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def calcular_atr(df, periodo=14):
    anterior = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - anterior).abs(),
        (df["low"] - anterior).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()


def calcular_adx(df, periodo=14):
    alta = df["high"].diff()
    baixa = -df["low"].diff()
    dm_positivo = alta.where((alta > baixa) & (alta > 0), 0.0)
    dm_negativo = baixa.where((baixa > alta) & (baixa > 0), 0.0)
    anterior = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - anterior).abs(),
        (df["low"] - anterior).abs()
    ], axis=1).max(axis=1)
    atr_suave = tr.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean().replace(0, np.nan)
    di_positivo = 100 * dm_positivo.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean() / atr_suave
    di_negativo = 100 * dm_negativo.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean() / atr_suave
    denominador = (di_positivo + di_negativo).replace(0, np.nan)
    dx = 100 * (di_positivo - di_negativo).abs() / denominador
    adx = dx.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    return di_positivo.fillna(0), di_negativo.fillna(0), adx.fillna(0)


def adicionar_indicadores(df):
    df = df.copy()
    for periodo in EMA_PERIODOS:
        df[f"ema{periodo}"] = df["close"].ewm(span=periodo, adjust=False).mean()
    df["rsi"] = calcular_rsi(df["close"], RSI_PERIODO)
    df["atr"] = calcular_atr(df, ATR_PERIODO)
    df["di_plus"], df["di_minus"], df["adx"] = calcular_adx(df, ADX_PERIODO)

    corpo = (df["close"] - df["open"]).abs()
    amplitude = (df["high"] - df["low"]).replace(0, np.nan)
    corpo_anterior = corpo.shift(1)
    df["engolfo_alta"] = (
        (df["close"] > df["open"]) & (df["close"].shift(1) < df["open"].shift(1))
        & (df["close"] >= df["open"].shift(1)) & (df["open"] <= df["close"].shift(1))
    )
    df["engolfo_baixa"] = (
        (df["close"] < df["open"]) & (df["close"].shift(1) > df["open"].shift(1))
        & (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))
    )
    sombra_inferior = df[["open", "close"]].min(axis=1) - df["low"]
    sombra_superior = df["high"] - df[["open", "close"]].max(axis=1)
    df["martelo"] = ((sombra_inferior >= corpo * 2) & (sombra_superior <= corpo) & (corpo / amplitude < 0.45)).fillna(False)
    df["estrela_cadente"] = ((sombra_superior >= corpo * 2) & (sombra_inferior <= corpo) & (corpo / amplitude < 0.45)).fillna(False)
    df["vela_forte"] = corpo > corpo_anterior * 1.3
    return df.replace([np.inf, -np.inf], np.nan)


def agregar_candles(df, segundos):
    base = df[["timestamp", "open", "high", "low", "close"]].copy()
    base["inicio"] = (base["timestamp"] // segundos) * segundos
    grupos = []
    esperado = segundos // INTERVALO_CANDLE
    for inicio, grupo in base.groupby("inicio", sort=True):
        if len(grupo) != esperado:
            continue
        timestamps_esperados = list(range(int(inicio), int(inicio) + segundos, INTERVALO_CANDLE))
        if grupo["timestamp"].tolist() != timestamps_esperados:
            continue
        if int(inicio) + segundos > int(time.time()):
            continue
        grupos.append({
            "timestamp": int(inicio), "open": float(grupo.iloc[0]["open"]),
            "high": float(grupo["high"].max()), "low": float(grupo["low"].min()),
            "close": float(grupo.iloc[-1]["close"])
        })
    return pd.DataFrame(grupos)


def obter_contexto(df, segundos):
    agregado = agregar_candles(df, segundos)
    # Exige dados suficientes para um contexto minimamente estavel.
    if len(agregado) < 8:
        return None
    agregado["ema3"] = agregado["close"].ewm(span=3, adjust=False).mean()
    agregado["ema8"] = agregado["close"].ewm(span=8, adjust=False).mean()
    u = agregado.iloc[-1]
    if u["ema3"] > u["ema8"]:
        return "ALTA"
    if u["ema3"] < u["ema8"]:
        return "BAIXA"
    return "LATERAL"


def analisar_tendencia(u):
    if u["ema3"] > u["ema30"] > u["ema60"] and u["close"] > u["ema200"]:
        return "ALTA"
    if u["ema3"] < u["ema30"] < u["ema60"] and u["close"] < u["ema200"]:
        return "BAIXA"
    if u["adx"] < ADX_LATERAL:
        return "LATERAL"
    return "TRANSICAO"


def detectar_rompimento(df):
    if len(df) < JANELA_ROMPIMENTO + 2:
        return "NAO CONFIRMADO"
    u = df.iloc[-1]
    anteriores = df.iloc[-JANELA_ROMPIMENTO - 1:-1]
    if u["close"] > float(anteriores["high"].max()):
        return "ALTA"
    if u["close"] < float(anteriores["low"].min()):
        return "BAIXA"
    return "NAO CONFIRMADO"


def calcular_entrada_retracao(df, janela=20):
    """Identifica zona de retração de 38,2%-61,8% em tendência já definida.

    Usa somente candles fechados. É um contexto de análise, não uma ordem
    nem garantia de reversão. A confirmação exige reação do candle fechado.
    """
    if len(df) < max(janela + 2, 80):
        return {"estado": "DADOS INSUFICIENTES", "lado": None,
                "percentual": None, "zona_inferior": None, "zona_superior": None}

    u = df.iloc[-1]
    anterior = df.iloc[-2]
    historico = df.iloc[-janela-1:-1]  # exclui o candle avaliado da estrutura
    topo = float(historico["high"].max())
    fundo = float(historico["low"].min())
    amplitude = topo - fundo
    if not np.isfinite(amplitude) or amplitude <= 0:
        return {"estado": "SEM ESTRUTURA", "lado": None,
                "percentual": None, "zona_inferior": None, "zona_superior": None}

    tendencia_alta = (u["ema3"] > u["ema30"] > u["ema60"]
                      and u["close"] > u["ema200"])
    tendencia_baixa = (u["ema3"] < u["ema30"] < u["ema60"]
                        and u["close"] < u["ema200"])

    if tendencia_alta:
        percentual = (topo - float(u["close"])) / amplitude
        zona_superior = topo - amplitude * 0.382
        zona_inferior = topo - amplitude * 0.618
        tocou_zona = float(u["low"]) <= zona_superior and float(u["close"]) >= zona_inferior
        reacao = (float(u["close"]) > float(u["open"])
                  and float(u["close"]) > float(anterior["close"]))
        if tocou_zona and reacao:
            estado = "COMPRA — RETRACAO CONFIRMADA"
        elif tocou_zona:
            estado = "ZONA DE COMPRA — AGUARDAR REACAO"
        elif percentual < 0.382:
            estado = "AGUARDAR RETRACAO"
        elif percentual > 0.618:
            estado = "RETRACAO PROFUNDA — CAUTELA"
        else:
            estado = "AVALIANDO RETRACAO"
        return {"estado": estado, "lado": "COMPRA", "percentual": percentual * 100,
                "zona_inferior": zona_inferior, "zona_superior": zona_superior}

    if tendencia_baixa:
        percentual = (float(u["close"]) - fundo) / amplitude
        zona_inferior = fundo + amplitude * 0.382
        zona_superior = fundo + amplitude * 0.618
        tocou_zona = float(u["high"]) >= zona_inferior and float(u["close"]) <= zona_superior
        reacao = (float(u["close"]) < float(u["open"])
                  and float(u["close"]) < float(anterior["close"]))
        if tocou_zona and reacao:
            estado = "VENDA — RETRACAO CONFIRMADA"
        elif tocou_zona:
            estado = "ZONA DE VENDA — AGUARDAR REACAO"
        elif percentual < 0.382:
            estado = "AGUARDAR RETRACAO"
        elif percentual > 0.618:
            estado = "RETRACAO PROFUNDA — CAUTELA"
        else:
            estado = "AVALIANDO RETRACAO"
        return {"estado": estado, "lado": "VENDA", "percentual": percentual * 100,
                "zona_inferior": zona_inferior, "zona_superior": zona_superior}

    return {"estado": "SEM TENDENCIA DEFINIDA", "lado": None,
            "percentual": None, "zona_inferior": None, "zona_superior": None}


def calcular_sinal(df, contexto_1m, contexto_5m):
    u = df.iloc[-1]
    compra, venda = 0, 0
    motivos_compra, motivos_venda = [], []

    def pontuar(condicao, pontos, lado, motivo):
        nonlocal compra, venda
        if condicao:
            if lado == "C":
                compra += pontos
                motivos_compra.append(motivo)
            else:
                venda += pontos
                motivos_venda.append(motivo)

    pontuar(u["ema3"] > u["ema13"], 1, "C", "EMA3 acima EMA13")
    pontuar(u["ema3"] < u["ema13"], 1, "V", "EMA3 abaixo EMA13")
    pontuar(u["ema13"] > u["ema21"], 1, "C", "EMA13 acima EMA21")
    pontuar(u["ema13"] < u["ema21"], 1, "V", "EMA13 abaixo EMA21")
    pontuar(u["close"] > u["ema50"], 1, "C", "Preco acima EMA50")
    pontuar(u["close"] < u["ema50"], 1, "V", "Preco abaixo EMA50")
    pontuar(u["close"] > u["ema200"], 1, "C", "Preco acima EMA200")
    pontuar(u["close"] < u["ema200"], 1, "V", "Preco abaixo EMA200")
    pontuar(u["di_plus"] > u["di_minus"], 1, "C", "DI+ dominante")
    pontuar(u["di_minus"] > u["di_plus"], 1, "V", "DI- dominante")
    pontuar(52 <= u["rsi"] <= 70, 1, "C", "RSI favorece alta")
    pontuar(30 <= u["rsi"] <= 48, 1, "V", "RSI favorece baixa")
    pontuar(bool(u["engolfo_alta"]), 1, "C", "Engolfo de alta")
    pontuar(bool(u["engolfo_baixa"]), 1, "V", "Engolfo de baixa")
    pontuar(bool(u["martelo"]), 1, "C", "Martelo")
    pontuar(bool(u["estrela_cadente"]), 1, "V", "Estrela cadente")

    rompimento = detectar_rompimento(df)
    pontuar(rompimento == "ALTA", 2, "C", "Rompimento de alta")
    pontuar(rompimento == "BAIXA", 2, "V", "Rompimento de baixa")
    pontuar(contexto_1m == "ALTA", 1, "C", "Contexto M1 em alta")
    pontuar(contexto_1m == "BAIXA", 1, "V", "Contexto M1 em baixa")
    pontuar(contexto_5m == "ALTA", 1, "C", "Contexto M5 em alta")
    pontuar(contexto_5m == "BAIXA", 1, "V", "Contexto M5 em baixa")

    if pd.notna(u["atr"]) and u["atr"] > 0:
        esticamento = abs(u["close"] - u["ema21"]) / u["atr"]
        if esticamento > MAX_ESTICAMENTO_ATR:
            compra = max(0, compra - 1)
            venda = max(0, venda - 1)

    vantagem = abs(compra - venda)
    if compra >= SCORE_MINIMO and compra - venda >= VANTAGEM_MINIMA:
        sinal, motivos = "COMPRA", motivos_compra
    elif venda >= SCORE_MINIMO and venda - compra >= VANTAGEM_MINIMA:
        sinal, motivos = "VENDA", motivos_venda
    else:
        sinal, motivos = "AGUARDAR", ["Confluencia insuficiente"]

    return {
        "sinal": sinal, "compra": int(compra), "venda": int(venda),
        "vantagem": int(vantagem), "rompimento": rompimento,
        "tendencia": analisar_tendencia(u), "motivos": motivos,
        "contexto_1m": contexto_1m or "INDISPONIVEL",
        "contexto_5m": contexto_5m or "INDISPONIVEL"
    }



def calcular_motor_quantitativo(df, info):
    """Ensemble quantitativo adaptativo, leve e explicavel para Pydroid.

    Combina sinais normalizados em escalas comparaveis, ajusta pesos por regime
    e reporta concordancia/conflito. Nao e um modelo treinado nem uma probabilidade.
    Usa apenas candles fechados disponiveis em df.
    """
    if len(df) < 80:
        return {"direcao": "INDEFINIDA", "forca": 0, "regime": "DADOS INSUFICIENTES",
                "momentum": 0.0, "concordancia": 0, "conflito": False,
                "componentes": {}, "indice": 0.0, "incerteza": 100}

    u = df.iloc[-1]
    atr = float(u["atr"]) if pd.notna(u["atr"]) else 0.0
    if not np.isfinite(atr) or atr <= 0:
        return {"direcao": "INDEFINIDA", "forca": 0, "regime": "ATR INDISPONIVEL",
                "momentum": 0.0, "concordancia": 0, "conflito": False,
                "componentes": {}, "indice": 0.0, "incerteza": 100}

    def limitar(valor, teto=1.0):
        if not np.isfinite(valor):
            return 0.0
        return float(np.clip(valor, -teto, teto))

    # Retornos de varias escalas, expressos em unidades de ATR.
    mom3 = limitar((float(u["close"]) - float(df.iloc[-4]["close"])) / atr / 1.2)
    mom6 = limitar((float(u["close"]) - float(df.iloc[-7]["close"])) / atr / 1.8)
    mom12 = limitar((float(u["close"]) - float(df.iloc[-13]["close"])) / atr / 2.5)
    mom30 = limitar((float(u["close"]) - float(df.iloc[-31]["close"])) / atr / 4.0)
    slope_fast = limitar((float(u["ema13"]) - float(df.iloc[-6]["ema13"])) / atr / 0.8)
    slope_slow = limitar((float(u["ema60"]) - float(df.iloc[-13]["ema60"])) / atr / 1.2)
    di_balance = limitar((float(u["di_plus"]) - float(u["di_minus"])) / 40.0)
    rsi_balance = limitar((float(u["rsi"]) - 50.0) / 25.0)

    janela = df.iloc[-31:-1]
    topo, fundo = float(janela["high"].max()), float(janela["low"].min())
    faixa = max(topo - fundo, atr)
    posicao_faixa = limitar(((float(u["close"]) - (topo + fundo) / 2.0) / faixa) * 2.0)
    corpo = limitar((float(u["close"]) - float(u["open"])) / atr / 0.8)
    breakout = 1.0 if info.get("rompimento") == "ALTA" else (-1.0 if info.get("rompimento") == "BAIXA" else 0.0)

    atr_series = df["atr"].dropna().tail(100)
    atr_mediana = float(atr_series.median()) if not atr_series.empty else atr
    razao_vol = atr / atr_mediana if atr_mediana > 0 else 1.0
    adx = float(u["adx"])
    if adx < ADX_LATERAL and razao_vol < 1.35:
        regime = "LATERAL"
    elif razao_vol >= 1.50:
        regime = "VOLATILIDADE ALTA"
    elif adx >= ADX_TENDENCIA:
        regime = "TENDENCIA"
    else:
        regime = "TRANSICAO"

    # Pesos explicitos e limitados. Pesos por regime nao sao ajustados com dados futuros.
    if regime == "TENDENCIA":
        pesos = {"mom3": .08, "mom6": .14, "mom12": .14, "mom30": .12,
                 "slope_fast": .13, "slope_slow": .15, "di": .10, "rsi": .05,
                 "faixa": .04, "corpo": .02, "rompimento": .03}
    elif regime == "LATERAL":
        pesos = {"mom3": .12, "mom6": .10, "mom12": .04, "mom30": .02,
                 "slope_fast": .07, "slope_slow": .02, "di": .05, "rsi": .12,
                 "faixa": .20, "corpo": .06, "rompimento": .22}
    elif regime == "VOLATILIDADE ALTA":
        pesos = {"mom3": .08, "mom6": .10, "mom12": .10, "mom30": .08,
                 "slope_fast": .08, "slope_slow": .08, "di": .10, "rsi": .06,
                 "faixa": .08, "corpo": .08, "rompimento": .16}
    else:
        pesos = {"mom3": .10, "mom6": .12, "mom12": .10, "mom30": .08,
                 "slope_fast": .12, "slope_slow": .10, "di": .10, "rsi": .08,
                 "faixa": .08, "corpo": .06, "rompimento": .06}

    componentes = {"mom3": mom3, "mom6": mom6, "mom12": mom12, "mom30": mom30,
                   "slope_fast": slope_fast, "slope_slow": slope_slow,
                   "di": di_balance, "rsi": rsi_balance, "faixa": posicao_faixa,
                   "corpo": corpo, "rompimento": breakout}
    soma_pesos = sum(pesos.values()) or 1.0
    indice = float(np.clip(sum(componentes[k] * pesos[k] for k in pesos) / soma_pesos, -1.0, 1.0))
    direcao = "ALTA" if indice >= 0.15 else ("BAIXA" if indice <= -0.15 else "NEUTRA")
    forca = int(round(abs(indice) * 100))

    lado_motor = 1 if direcao == "ALTA" else (-1 if direcao == "BAIXA" else 0)
    votos = [v for v in componentes.values() if abs(v) >= 0.12]
    alinhadas = sum(1 for v in votos if lado_motor and v * lado_motor > 0)
    concordancia = int(round(100 * alinhadas / len(votos))) if votos else 0
    lados = [1 if v > .12 else (-1 if v < -.12 else 0) for v in votos]
    direcoes_ativas = {v for v in lados if v}
    dispersao = (len([v for v in lados if v != 0]) - max(
        [len([x for x in lados if x == lado]) for lado in (-1, 1)] or [0]))
    incerteza = int(np.clip(100 - forca * 0.55 - concordancia * 0.35 + max(0, dispersao) * 5, 0, 100))

    lado_sinal = 1 if info.get("sinal") == "COMPRA" else (-1 if info.get("sinal") == "VENDA" else 0)
    conflito = bool(lado_sinal and lado_motor and lado_sinal != lado_motor and forca >= 15)
    return {"direcao": direcao, "forca": forca, "regime": regime,
            "momentum": float(mom6), "concordancia": concordancia,
            "conflito": conflito, "componentes": componentes,
            "indice": indice, "incerteza": incerteza,
            "razao_volatilidade": float(razao_vol), "votos_ativos": len(votos)}


def avaliar_continuidade(df, sinal_atual, sinal_anterior):
    if sinal_atual == "AGUARDAR":
        return "SEM CONFIRMACAO"
    u, anterior = df.iloc[-1], df.iloc[-2]
    if sinal_atual == "COMPRA":
        alinhado = u["ema3"] > u["ema13"] and u["di_plus"] > u["di_minus"] and u["close"] > u["ema21"]
        impulso = u["close"] >= anterior["close"]
        risco = u["close"] < u["ema21"] or u["di_minus"] > u["di_plus"]
    else:
        alinhado = u["ema3"] < u["ema13"] and u["di_minus"] > u["di_plus"] and u["close"] < u["ema21"]
        impulso = u["close"] <= anterior["close"]
        risco = u["close"] > u["ema21"] or u["di_plus"] > u["di_minus"]
    if not alinhado:
        return "EM RISCO" if sinal_anterior == sinal_atual else "ENFRAQUECENDO"
    if risco:
        return "EM RISCO"
    if sinal_anterior not in (None, "", sinal_atual):
        return "MANTIDO" if impulso else "ENFRAQUECENDO"
    return "MANTIDO" if impulso else "ENFRAQUECENDO"


def calcular_suporte_resistencia(df):
    janela = df.tail(JANELA_SR)
    return {"suporte": float(janela["low"].min()), "resistencia": float(janela["high"].max())}


def calcular_projecoes(df, sinal):
    """Calcula ATR(14), níveis de 1/2/3/5 ATR e projeções heurísticas por tempo.

    Os múltiplos ATR representam distâncias de volatilidade, não probabilidades
    nem garantias de que o preço alcançará esses níveis.
    """
    u = df.iloc[-1]
    preco, atr = float(u["close"]), float(u["atr"])
    if not np.isfinite(atr) or atr <= 0:
        raise ValueError("ATR invalido; projecoes interrompidas.")

    # Níveis em ambas as direções permanecem disponíveis mesmo quando o sinal é AGUARDAR.
    niveis_atr = {}
    for multiplo in (1, 2, 3, 5):
        distancia = atr * multiplo
        niveis_atr[multiplo] = {
            "distancia_preco": float(distancia),
            "compra": float(preco + distancia),
            "venda": float(preco - distancia),
        }

    if sinal not in ("COMPRA", "VENDA"):
        return {"atr": atr, "niveis_atr": niveis_atr, "alvo_curto": None,
                "alvo_longo": None, "detalhes": {}, "fibonacci": {}}

    direcao = 1 if sinal == "COMPRA" else -1
    detalhes = {}
    for minutos in HORIZONTES_MINUTOS:
        barras = (minutos * 60) // INTERVALO_CANDLE
        distancia = atr * math.sqrt(barras) * 0.45
        distancia_atr = distancia / atr
        detalhes[minutos] = {
            "preco": float(preco + direcao * distancia),
            "distancia_preco": float(distancia),
            "distancia_atr": float(distancia_atr),
            "multiplo_atr_aproximado": int(round(distancia_atr)),
        }

    topo = float(df.tail(JANELA_ESTRUTURA_LONGA)["high"].max())
    fundo = float(df.tail(JANELA_ESTRUTURA_LONGA)["low"].min())
    amplitude = max(topo - fundo, atr)
    if sinal == "COMPRA":
        fibonacci = {"1.272": float(topo + amplitude * 0.272), "1.618": float(topo + amplitude * 0.618), "2.000": float(topo + amplitude)}
    else:
        fibonacci = {"1.272": float(fundo - amplitude * 0.272), "1.618": float(fundo - amplitude * 0.618), "2.000": float(fundo - amplitude)}
    return {"atr": atr, "niveis_atr": niveis_atr, "alvo_curto": detalhes[2]["preco"],
            "alvo_longo": detalhes[5]["preco"], "detalhes": detalhes, "fibonacci": fibonacci}


def classificar_alvo(info, continuidade, projecoes, df):
    if info["sinal"] == "AGUARDAR":
        return "ALVO NAO DEFINIDO"
    u, sinal = df.iloc[-1], info["sinal"]
    if sinal == "COMPRA":
        alinhado = u["ema3"] > u["ema13"] and u["di_plus"] > u["di_minus"]
        rompimento_alinhado = info["rompimento"] == "ALTA"
        forca = info["compra"]
    else:
        alinhado = u["ema3"] < u["ema13"] and u["di_minus"] > u["di_plus"]
        rompimento_alinhado = info["rompimento"] == "BAIXA"
        forca = info["venda"]
    if forca >= SCORE_MINIMO + 2 and u["adx"] >= ADX_TENDENCIA and alinhado and (rompimento_alinhado or continuidade == "MANTIDO"):
        return "ALVO LONGO"
    if forca >= SCORE_MINIMO and alinhado and continuidade in ("MANTIDO", "ENFRAQUECENDO"):
        return "ALVO CURTO"
    return "ALVO NAO DEFINIDO"


def registrar_sinal(ativo, df, info, continuidade, tipo_alvo, projecoes):
    u = df.iloc[-1]
    registro = {
        "timestamp_candle": int(u["timestamp"]), "hora_candle_local": u["hora_local"],
        "hora_candle_utc": u["hora_utc"], "hora_processamento_local": hora_local(),
        "ativo": ativo, "preco": float(u["close"]), "sinal": info["sinal"],
        "tipo_alvo": tipo_alvo, "continuidade": continuidade,
        "tendencia": info["tendencia"], "rompimento": info["rompimento"],
        "score_compra": info["compra"], "score_venda": info["venda"],
        "motor_direcao": info.get("motor", {}).get("direcao", "INDEFINIDA"),
        "motor_forca": info.get("motor", {}).get("forca", 0),
        "motor_regime": info.get("motor", {}).get("regime", "INDEFINIDO"),
        "motor_concordancia": info.get("motor", {}).get("concordancia", 0),
        "motor_conflito": info.get("motor", {}).get("conflito", False),
        "motor_indice": info.get("motor", {}).get("indice", 0.0),
        "motor_incerteza_tecnica": info.get("motor", {}).get("incerteza", 100),
        "motor_votos_ativos": info.get("motor", {}).get("votos_ativos", 0),
        "motor_razao_volatilidade": info.get("motor", {}).get("razao_volatilidade", 1.0),
        "rsi": float(u["rsi"]), "adx": float(u["adx"]), "atr": float(u["atr"]),
        "alvo_curto": projecoes["alvo_curto"], "alvo_longo": projecoes["alvo_longo"]
    }
    for nome, valor in info.get("motor", {}).get("componentes", {}).items():
        registro[f"motor_{nome}"] = float(valor)
    for minutos, alvo in projecoes["detalhes"].items():
        registro[f"alvo_{minutos}m"] = alvo["preco"]
        registro[f"distancia_{minutos}m_preco"] = alvo["distancia_preco"]
        registro[f"distancia_{minutos}m_atr"] = alvo["distancia_atr"]
    salvar_csv(nome_arquivo(ativo, "sinais"), registro)


def salvar_candles(ativo, df):
    df.to_csv(nome_arquivo(ativo, "candles"), index=False, encoding="utf-8")


def obter_candles_horas(api, ativo):
    """Obtém candles reais de 1 minuto para estimar cenários de 1 a 4 horas."""
    dados = api.get_candles(ativo, INTERVALO_CANDLE_HORAS,
                            QUANTIDADE_CANDLES_HORAS, int(time.time()))
    if not dados or len(dados) < MINIMO_CANDLES_HORAS:
        raise ValueError("Historico insuficiente de candles de 1 minuto para projecao horaria.")
    df = pd.DataFrame(dados).copy()
    obrigatorias = {"from", "open", "close", "min", "max"}
    if not obrigatorias.issubset(df.columns):
        raise ValueError("Formato inesperado nos candles de 1 minuto.")
    df = df.rename(columns={"from": "timestamp", "min": "low", "max": "high"})
    for coluna in ("timestamp", "open", "high", "low", "close"):
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    agora = time.time()
    df = df[df["timestamp"] + INTERVALO_CANDLE_HORAS <= agora - 0.25].copy()
    if len(df) < MINIMO_CANDLES_HORAS:
        raise ValueError("Poucos candles fechados de 1 minuto apos validacao.")
    if ((df["high"] < df["low"]).any()
            or (df["high"] < df[["open", "close"]].max(axis=1)).any()
            or (df["low"] > df[["open", "close"]].min(axis=1)).any()):
        raise ValueError("Candles de 1 minuto inconsistentes.")
    dif = df["timestamp"].diff().dropna()
    falhas = int((dif > INTERVALO_CANDLE_HORAS * 2).sum())
    if falhas > max(3, int(len(df) * 0.03)):
        raise ValueError("Muitos intervalos ausentes no historico de 1 minuto.")
    df["hora_local"] = df["timestamp"].apply(lambda x: formatar_hora(x, utc=False))
    return df.tail(QUANTIDADE_CANDLES_HORAS).reset_index(drop=True)


def calcular_projecoes_horarias(df_minuto, preco_atual):
    """Cenarios heurísticos 1h-4h usando somente candles reais fechados de 1 minuto."""
    if df_minuto is None or len(df_minuto) < MINIMO_CANDLES_HORAS:
        raise ValueError("Dados insuficientes para cenarios horarios.")
    h = df_minuto.copy()
    h["ema20"] = h["close"].ewm(span=20, adjust=False).mean()
    h["ema50"] = h["close"].ewm(span=50, adjust=False).mean()
    h["ema200"] = h["close"].ewm(span=200, adjust=False).mean()
    h["rsi"] = calcular_rsi(h["close"], 14)
    h["atr"] = calcular_atr(h, 14)
    h["di_plus"], h["di_minus"], h["adx"] = calcular_adx(h, 14)
    u = h.iloc[-1]
    atr = float(u["atr"])
    if not np.isfinite(atr) or atr <= 0:
        raise ValueError("ATR horario indisponivel; cenarios interrompidos.")

    pontos_alta = 0
    pontos_baixa = 0
    if u["ema20"] > u["ema50"]: pontos_alta += 1
    elif u["ema20"] < u["ema50"]: pontos_baixa += 1
    if u["close"] > u["ema200"]: pontos_alta += 1
    elif u["close"] < u["ema200"]: pontos_baixa += 1
    if u["di_plus"] > u["di_minus"]: pontos_alta += 1
    elif u["di_minus"] > u["di_plus"]: pontos_baixa += 1
    if u["rsi"] >= 55: pontos_alta += 1
    elif u["rsi"] <= 45: pontos_baixa += 1
    if len(h) >= 6:
        variacao = float(u["close"] - h.iloc[-6]["close"])
        if variacao > 0: pontos_alta += 1
        elif variacao < 0: pontos_baixa += 1

    if pontos_alta >= 3 and pontos_alta - pontos_baixa >= 2:
        vies = "ALTA"
        pontos = pontos_alta
    elif pontos_baixa >= 3 and pontos_baixa - pontos_alta >= 2:
        vies = "BAIXA"
        pontos = pontos_baixa
    else:
        vies = "LATERAL / SEM CONFLUENCIA"
        pontos = max(pontos_alta, pontos_baixa)

    # ATR(14) de candles de 1 minuto; raiz do tempo e fator conservador.
    # Isto produz faixas ilustrativas, nao probabilidades nem alvos garantidos.
    horizontes = {}
    for horas in HORIZONTES_HORAS:
        minutos = horas * 60
        dist = atr * math.sqrt(minutos) * 0.45
        if vies == "ALTA":
            centro = float(preco_atual + dist)
            inferior, superior = float(preco_atual), float(preco_atual + dist * 1.5)
        elif vies == "BAIXA":
            centro = float(preco_atual - dist)
            inferior, superior = float(preco_atual - dist * 1.5), float(preco_atual)
        else:
            centro = None
            inferior, superior = float(preco_atual - dist), float(preco_atual + dist)
        horizontes[horas] = {
            "centro": centro, "limite_inferior": inferior,
            "limite_superior": superior, "distancia": float(dist),
            "distancia_atr_1m": float(dist / atr),
        }
    qualidade = "FORTE" if pontos >= 4 and float(u["adx"]) >= 20 else (
        "MODERADA" if pontos >= 3 else "FRACA")
    return {
        "vies": vies, "pontos_alta": pontos_alta, "pontos_baixa": pontos_baixa,
        "qualidade": qualidade, "atr_1m": atr, "adx": float(u["adx"]),
        "rsi": float(u["rsi"]), "ema20": float(u["ema20"]),
        "ema50": float(u["ema50"]), "ema200": float(u["ema200"]),
        "timestamp": int(u["timestamp"]), "horizontes": horizontes,
    }


def mostrar_painel(ativo, df, info, continuidade, tipo_alvo, projecoes, projecoes_horarias, falhas, coleta_ms=0.0, calculo_ms=0.0):
    """Painel Hunter Minimalista: compacto, sem alterar os calculos do QMS."""
    u = df.iloc[-1]
    sr = calcular_suporte_resistencia(df)
    limpar_tela()

    # Normalizacao visual do score existente: maximo teorico de 12 pontos por lado.
    # Isto e uma escala de score, nao uma probabilidade de acerto.
    score_lado = info["compra"] if info["sinal"] == "COMPRA" else info["venda"]
    forca = max(0, min(100, round((score_lado / 12.0) * 100)))
    if info["sinal"] == "COMPRA":
        direcao, cor_direcao = "ALTA ^", "1;92"
    elif info["sinal"] == "VENDA":
        direcao, cor_direcao = "BAIXA v", "1;91"
    else:
        direcao, cor_direcao = "AGUARDAR", "1;93"

    if info["rompimento"] == "ALTA":
        rompimento = "TOPO ROMPIDO ^"
        cor_rompimento = "92"
    elif info["rompimento"] == "BAIXA":
        rompimento = "FUNDO ROMPIDO v"
        cor_rompimento = "91"
    else:
        rompimento = "SEM ROMPIMENTO"
        cor_rompimento = "93"

    print(cor("=" * 38, "96"))
    print(cor(" QMS / HUNTER  |  V5.3 LS", "1;96"))
    print(cor(" LARGE SCALE | PAINEL MINIMALISTA", "96"))
    print(cor("=" * 38, "96"))
    print(f"Ativo: {ativo} | Candle fechado: {INTERVALO_CANDLE}s")
    print(f"Hora: {hora_local()}")
    idade_candle = max(0.0, time.time() - (int(u["timestamp"]) + INTERVALO_CANDLE))
    print(f"LATENCIA: coleta {coleta_ms:.0f} ms | calculo {calculo_ms:.0f} ms | idade do candle {idade_candle:.1f} s")
    if idade_candle > INTERVALO_CANDLE * 1.5:
        print(cor("ALERTA: candle recebido esta antigo; sinal pode estar atrasado", "1;93"))
    print(cor(f"DIRECAO: {direcao}", cor_direcao))
    print(f"FORCA DO SCORE: {forca}/100 | Compra {info['compra']} x Venda {info['venda']}")
    print(f"Vantagem: {info['vantagem']} pontos | Alvo: {tipo_alvo}")
    print(cor("-" * 38, "90"))

    print(cor("ROMPIMENTO", "1;96"))
    print(cor(rompimento, f"1;{cor_rompimento}"))
    print(f"Continuidade: {continuidade}")
    print(f"Tendencia: {info['tendencia']}")
    retracao = info.get("retracao", {})
    estado_retracao = retracao.get("estado", "INDISPONIVEL")
    cor_retracao = "1;92" if "CONFIRMADA" in estado_retracao else ("1;93" if "ZONA" in estado_retracao or "CAUTELA" in estado_retracao else "96")
    print(cor("ENTRADA POR RETRACAO", "1;96"))
    print(cor(estado_retracao, cor_retracao))
    if retracao.get("percentual") is not None:
        print(f"Retraimento: {retracao['percentual']:.1f}% | Faixa 38,2%-61,8%")
        print(f"Zona tecnica: {retracao['zona_inferior']:.6f} - {retracao['zona_superior']:.6f}")
    print("Confirmacao por candle fechado; nao e ordem automatica.")
    motor = info.get("motor", {})
    if motor:
        estado_motor = f"{motor['direcao']} {motor['forca']}/100 | {motor['regime']}"
        print(cor(f"MOTOR QUANTITATIVO: {estado_motor}", "1;96"))
        print(f"Concordancia: {motor['concordancia']}% | Momentum: {motor['momentum']:+.2f} ATR")
        print(f"Incerteza tecnica: {motor.get('incerteza', 100)}% | Evidencias ativas: {motor.get('votos_ativos', 0)}")
        print(f"Volatilidade relativa: {motor.get('razao_volatilidade', 1.0):.2f}x")
        if motor["conflito"]:
            print(cor("ALERTA: motor quantitativo diverge do sinal base", "1;93"))

    print(cor("DADOS TECNICOS", "1;96"))
    print(f"Preco: {u['close']:.6f}")
    print(f"EMA 3 / 30: {u['ema3']:.6f} / {u['ema30']:.6f}")
    print(f"EMA 60 / 200: {u['ema60']:.6f} / {u['ema200']:.6f}")
    print(f"RSI {u['rsi']:.1f} | ADX {u['adx']:.1f} | DI+ {u['di_plus']:.1f} / DI- {u['di_minus']:.1f}")
    # Exibe ATR em multiplos inteiros para leitura rapida, sem esconder o valor real usado.
    atr_pips = float(u['atr']) * (10000 if 'JPY' not in ativo.upper() else 100)
    print(f"ATR: {atr_pips:.0f} pips aprox. | Base: {u['atr']:.6f}")
    print(f"Suporte: {sr['suporte']:.6f}")
    print(f"Resistencia: {sr['resistencia']:.6f}")
    print(cor("-" * 38, "90"))

    print(cor("ALCANCE ESTIMADO", "1;96"))
    for minutos in HORIZONTES_MINUTOS:
        alvo = projecoes["detalhes"].get(minutos)
        if alvo:
            mult = max(1, int(alvo.get("multiplo_atr_aproximado", round(alvo["distancia_atr"]))))
            print(f"{minutos}m: {alvo['preco']:.6f}  | {mult} ATR")
        else:
            print(f"{minutos}m: sem projecao direcional")
    if projecoes.get("fibonacci"):
        fib = projecoes["fibonacci"]
        print(f"Extensoes: 1.272 {fib['1.272']:.6f} | 1.618 {fib['1.618']:.6f}")
    print(cor("CONTEXTO 1H A 4H", "1;96"))
    if projecoes_horarias:
        ph = projecoes_horarias
        print(f"Vies: {ph['vies']} | Qualidade: {ph['qualidade']}")
        for horas in HORIZONTES_HORAS:
            c = ph["horizontes"][horas]
            if c["centro"] is None:
                print(f"{horas}h: faixa {c['limite_inferior']:.6f}-{c['limite_superior']:.6f}")
            else:
                print(f"{horas}h: {c['centro']:.6f} ({c['limite_inferior']:.6f}-{c['limite_superior']:.6f})")
    else:
        print("Indisponivel: dados horarios insuficientes/inconsistentes")

    print(cor("-" * 38, "90"))
    if info["sinal"] == "AGUARDAR":
        print(cor("LEITURA: AGUARDAR CONFLUENCIA", "1;93"))
    elif continuidade == "EM RISCO":
        print(cor("LEITURA: SINAL EM RISCO - CAUTELA", "1;93"))
    else:
        print(cor(f"LEITURA: {direcao} | {continuidade}", cor_direcao))
    print(f"Falhas: {falhas}/{MAX_FALHAS}")
    print(cor("SOMENTE LEITURA | SEM ORDENS | SEM MARTINGALE", "1;97"))
    print("Score normalizado nao e probabilidade; projecoes sao estimativas.")


def validar_pendentes(ativo, pendentes, df):
    """Valida horizontes apos decorrido o tempo; sem inferir candles ausentes."""
    restantes = []
    timestamps = df["timestamp"].astype(int)
    ultimo_timestamp = int(timestamps.iloc[-1])
    for item in pendentes:
        tempo_decorrido = ultimo_timestamp - item["timestamp"]
        for minutos in HORIZONTES_MINUTOS:
            if minutos in item["validados"] or tempo_decorrido < minutos * 60:
                continue
            inicio, fim = item["timestamp"], item["timestamp"] + minutos * 60
            janela = df[(df["timestamp"] > inicio) & (df["timestamp"] <= fim)]
            # Exige janela completa de candles de 10 segundos para validar.
            esperado = (minutos * 60) // INTERVALO_CANDLE
            if len(janela) < esperado or int(janela.iloc[-1]["timestamp"]) < fim - INTERVALO_CANDLE:
                continue
            entrada = item["preco"]
            alvo = item["alvos"][minutos]
            direcao = 1 if item["sinal"] == "COMPRA" else -1
            final = float(janela.iloc[-1]["close"])
            if direcao == 1:
                favoravel = float(janela["high"].max()) - entrada
                adverso = entrada - float(janela["low"].min())
                tocou = bool((janela["high"] >= alvo).any())
            else:
                favoravel = entrada - float(janela["low"].min())
                adverso = float(janela["high"].max()) - entrada
                tocou = bool((janela["low"] <= alvo).any())
            salvar_csv(nome_arquivo(ativo, "validacao"), {
                "timestamp_sinal": item["timestamp"], "hora_sinal_local": item["hora"],
                "ativo": ativo, "sinal": item["sinal"], "horizonte_minutos": minutos,
                "preco_entrada": entrada, "alvo_estimado": alvo,
                "preco_final_horizonte": final, "alvo_tocado": tocou,
                "movimento_favoravel": favoravel, "movimento_adverso": adverso
            })
            item["validados"].add(minutos)
        if len(item["validados"]) < len(HORIZONTES_MINUTOS):
            # Se a janela antiga saiu dos candles carregados, nao inventar resultado.
            if ultimo_timestamp - item["timestamp"] <= (QUANTIDADE_CANDLES - 2) * INTERVALO_CANDLE:
                restantes.append(item)
    return restantes


def executar_qms():
    ativo = selecionar_ativo()
    api = conectar()
    falhas = 0
    ultimo_candle_processado = None
    ultimo_sinal_registrado = None
    ultimo_tipo_alvo_registrado = None
    sinal_anterior = None
    pendentes = []
    projecoes_horarias = None
    ultima_atualizacao_horaria = 0.0
    print(f"\nConectado. Ativo selecionado: {ativo}")
    time.sleep(1)

    while True:
        try:
            if not conexao_ativa(api):
                logging.warning("Conexao perdida; tentando reconectar.")
                resultado = api.connect()
                conectado = resultado[0] if isinstance(resultado, tuple) else bool(resultado)
                if not conectado:
                    raise ConnectionError("Falha ao reconectar.")

            inicio_coleta = time.monotonic()
            candles = obter_candles(api, ativo)
            coleta_ms = (time.monotonic() - inicio_coleta) * 1000.0
            timestamp_atual = int(candles.iloc[-1]["timestamp"])
            if timestamp_atual == ultimo_candle_processado:
                time.sleep(INTERVALO_LOOP)
                continue

            # Atualiza o contexto de 1 minuto no maximo uma vez por minuto.
            if time.time() - ultima_atualizacao_horaria >= 60 or projecoes_horarias is None:
                try:
                    candles_horas = obter_candles_horas(api, ativo)
                    projecoes_horarias = calcular_projecoes_horarias(
                        candles_horas, float(candles.iloc[-1]["close"])
                    )
                    ultima_atualizacao_horaria = time.time()
                except Exception as erro_horario:
                    logging.warning("Projecao horaria indisponivel: %s", erro_horario)
                    projecoes_horarias = None
                    ultima_atualizacao_horaria = time.time()

            inicio_calculo = time.monotonic()
            df = adicionar_indicadores(candles)
            u = df.iloc[-1]
            criticas = ["ema3", "ema13", "ema21", "ema30", "ema50", "ema60", "ema200", "rsi", "atr", "adx", "di_plus", "di_minus"]
            if any(pd.isna(u[c]) for c in criticas):
                raise ValueError("Indicadores incompletos no candle atual.")

            retracao = calcular_entrada_retracao(df)
            contexto_1m = obter_contexto(df, 60)
            contexto_5m = obter_contexto(df, 300)
            info = calcular_sinal(df, contexto_1m, contexto_5m)
            info["retracao"] = retracao
            info["motor"] = calcular_motor_quantitativo(df, info)
            continuidade = avaliar_continuidade(df, info["sinal"], sinal_anterior)
            projecoes = calcular_projecoes(df, info["sinal"])
            tipo_alvo = classificar_alvo(info, continuidade, projecoes, df)
            salvar_candles(ativo, candles)

            if info["sinal"] in ("COMPRA", "VENDA"):
                novo = (info["sinal"] != ultimo_sinal_registrado or tipo_alvo != ultimo_tipo_alvo_registrado)
                if novo:
                    registrar_sinal(ativo, df, info, continuidade, tipo_alvo, projecoes)
                    if projecoes["detalhes"]:
                        pendentes.append({
                            "timestamp": timestamp_atual, "hora": u["hora_local"],
                            "preco": float(u["close"]), "sinal": info["sinal"],
                            "alvos": {m: projecoes["detalhes"][m]["preco"] for m in HORIZONTES_MINUTOS},
                            "validados": set()
                        })
                    ultimo_sinal_registrado = info["sinal"]
                    ultimo_tipo_alvo_registrado = tipo_alvo

            pendentes = validar_pendentes(ativo, pendentes, df)
            calculo_ms = (time.monotonic() - inicio_calculo) * 1000.0
            mostrar_painel(ativo, df, info, continuidade, tipo_alvo, projecoes, projecoes_horarias, falhas, coleta_ms, calculo_ms)
            sinal_anterior = info["sinal"]
            ultimo_candle_processado = timestamp_atual
            falhas = 0
            time.sleep(INTERVALO_LOOP)

        except KeyboardInterrupt:
            print("\nQMS encerrado pelo usuario.")
            break
        except Exception as erro:
            falhas += 1
            logging.exception("Falha no ciclo de analise: %s", erro)
            print(f"\nFalha de analise {falhas}/{MAX_FALHAS}: {erro}")
            if falhas >= MAX_FALHAS:
                print("Limite de falhas atingido. Encerrando por seguranca.")
                break
            time.sleep(2)

    try:
        api.close_connect()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        executar_qms()
    except KeyboardInterrupt:
        print("\nPrograma encerrado.")
    except Exception as erro:
        logging.exception("Erro fatal: %s", erro)
        print(f"Erro fatal: {erro}")
