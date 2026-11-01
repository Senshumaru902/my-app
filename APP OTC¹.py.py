# ============================================================
# QMS QUANTUM FUTURE V5.3.7 — PREVISAO M1 + PROJECAO FOREX 15M OTC
# IQ OPTION / PYDROID 3
# SOMENTE ANALISE — SEM ORDENS AUTOMATICAS — SEM MARTINGALE
# ============================================================
# IMPORTANTE:
# - Usa candles reais obtidos pela API; analisa somente candles fechados.
# - Analisa somente a tendencia predominante do grafico atual (candles de M1).
# - Projecoes direcionais para 5 e 15 minutos, estimativas tecnicas, nao garantias.
# - Preve o proximo candle de M1 combinando tendencia, momentum, osciladores, volatilidade, estrutura e candlesticks.
# - Somente leitura: nao envia ordens e nao usa Martingale.
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


VERSAO = "QMS QUANTUM FUTURE V5.3.7 OTC — PREVISAO M1 + PROJECAO 15M"
ATIVO_FIXO = "EURUSD-OTC"
INTERVALO_CANDLE = 60
QUANTIDADE_CANDLES = 400
MINIMO_CANDLES = 220
INTERVALO_LOOP = 1.0
MAX_FALHAS = 12

EMA_PERIODOS = (3, 5, 8, 13, 21, 30, 50, 60, 200)
RSI_PERIODO = 14
ATR_PERIODO = 14
ADX_PERIODO = 14
VORTEX_PERIODO = 14
KROLL_ATR_PERIODO = 14
KROLL_CANAL_PERIODO = 9
KROLL_MULTIPLICADOR = 1.0

SCORE_MINIMO = 5
VANTAGEM_MINIMA = 2
ADX_TENDENCIA = 20.0
ADX_LATERAL = 17.0
MAX_ESTICAMENTO_ATR = 1.50
JANELA_ROMPIMENTO = 12
JANELA_SR = 60
JANELA_ESTRUTURA_LONGA = 180
HORIZONTES_MINUTOS = (5, 15)
HORIZONTES_HORAS = ()
INTERVALO_CANDLE_HORAS = 60  # modulo legado desativado nesta versao
QUANTIDADE_CANDLES_HORAS = 400
MINIMO_CANDLES_HORAS = 220

CSV_PREFIXO = "qms_v532_otc"
logging.basicConfig(
    filename="qms_v532_otc.log",
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
    """Ativo fixo: esta versao opera somente com dados EURUSD-OTC."""
    print("\nATIVO FIXO: EURUSD-OTC")
    print("Mercado OTC exclusivo — EURUSD convencional desabilitado.")
    return ATIVO_FIXO


def validar_ativo_otc(ativo):
    if ativo != ATIVO_FIXO:
        raise ValueError(
            f"Ativo bloqueado: {ativo}. Esta versao aceita somente {ATIVO_FIXO}."
        )


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
    validar_ativo_otc(ativo)
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
    # CORRECAO DE LATENCIA: nao subtrair um candle extra de M1 do relogio.
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

    # Vortex Indicator (14): movimento direcional positivo e negativo.
    vortex_vm_plus = (df["high"] - df["low"].shift(1)).abs()
    vortex_vm_minus = (df["low"] - df["high"].shift(1)).abs()
    vortex_tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    vortex_tr_sum = vortex_tr.rolling(
        VORTEX_PERIODO, min_periods=VORTEX_PERIODO
    ).sum().replace(0, np.nan)
    df["vortex_plus"] = (
        vortex_vm_plus.rolling(VORTEX_PERIODO, min_periods=VORTEX_PERIODO).sum()
        / vortex_tr_sum
    )
    df["vortex_minus"] = (
        vortex_vm_minus.rolling(VORTEX_PERIODO, min_periods=VORTEX_PERIODO).sum()
        / vortex_tr_sum
    )

    # Channel Kroll Stop: linhas de stop calculadas com ATR e extremos da janela.
    kroll_atr = calcular_atr(df, KROLL_ATR_PERIODO)
    topo_kroll = df["high"].rolling(
        KROLL_CANAL_PERIODO, min_periods=KROLL_CANAL_PERIODO
    ).max()
    fundo_kroll = df["low"].rolling(
        KROLL_CANAL_PERIODO, min_periods=KROLL_CANAL_PERIODO
    ).min()
    df["kroll_superior"] = topo_kroll - KROLL_MULTIPLICADOR * kroll_atr
    df["kroll_inferior"] = fundo_kroll + KROLL_MULTIPLICADOR * kroll_atr
    macd_rapida = df["close"].ewm(span=12, adjust=False).mean()
    macd_lenta = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = macd_rapida - macd_lenta
    df["macd_sinal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sinal"]

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

    # Indicadores adicionais para a previsao do proximo candle.
    media = df["close"].rolling(20, min_periods=20).mean()
    desvio = df["close"].rolling(20, min_periods=20).std(ddof=0)
    df["bb_media"] = media
    df["bb_superior"] = media + 2.0 * desvio
    df["bb_inferior"] = media - 2.0 * desvio
    menor = df["low"].rolling(14, min_periods=14).min()
    maior = df["high"].rolling(14, min_periods=14).max()
    faixa = (maior - menor).replace(0, np.nan)
    df["stoch_k"] = (100.0 * (df["close"] - menor) / faixa).clip(0, 100)
    df["stoch_d"] = df["stoch_k"].rolling(3, min_periods=3).mean()
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_media = tp.rolling(20, min_periods=20).mean()
    desvio_abs = tp.rolling(20, min_periods=20).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    ).replace(0, np.nan)
    df["cci"] = (tp - tp_media) / (0.015 * desvio_abs)
    df["roc"] = df["close"].pct_change(5) * 100.0

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


def decisao_vortex_kroll(u):
    """Uma unica decisao conjunta: Vortex confirma a posicao no Channel Kroll Stop."""
    valores = [
        u.get("vortex_plus", np.nan), u.get("vortex_minus", np.nan),
        u.get("kroll_superior", np.nan), u.get("kroll_inferior", np.nan)
    ]
    if not all(np.isfinite(float(v)) for v in valores):
        return 0, "SEM DADOS"
    if u["vortex_plus"] > u["vortex_minus"] and u["close"] > u["kroll_superior"]:
        return 1, "COMPRA CONFIRMADA"
    if u["vortex_minus"] > u["vortex_plus"] and u["close"] < u["kroll_inferior"]:
        return -1, "VENDA CONFIRMADA"
    if u["vortex_plus"] == u["vortex_minus"]:
        return 0, "VORTEX NEUTRO"
    return 0, "SEM CONFLUENCIA"


def calcular_sinal(df, contexto_1m=None, contexto_5m=None):
    """Decide apenas pela tendencia predominante do grafico atual.

    Os unicos dados usados sao candles fechados do timeframe configurado.
    M1/M5, padroes, Fibonacci, retracao e rompimento nao participam da decisao.
    """
    u = df.iloc[-1]
    anterior = df.iloc[-7]
    componentes = {}

    componentes["EMAs"] = (
        1 if u["ema3"] > u["ema13"] > u["ema30"] > u["ema60"]
        else (-1 if u["ema3"] < u["ema13"] < u["ema30"] < u["ema60"] else 0)
    )
    componentes["PRECO_EMA200"] = (
        1 if u["close"] > u["ema200"]
        else (-1 if u["close"] < u["ema200"] else 0)
    )
    componentes["DI"] = (
        1 if u["di_plus"] > u["di_minus"]
        else (-1 if u["di_minus"] > u["di_plus"] else 0)
    )
    componentes["MACD"] = (
        1 if u["macd_hist"] > 0
        else (-1 if u["macd_hist"] < 0 else 0)
    )
    componentes["MOMENTUM"] = (
        1 if u["close"] > anterior["close"]
        else (-1 if u["close"] < anterior["close"] else 0)
    )
    componentes["RSI"] = (
        1 if u["rsi"] > 52
        else (-1 if u["rsi"] < 48 else 0)
    )
    voto_vk, estado_vk = decisao_vortex_kroll(u)
    componentes["VORTEX_KROLL"] = voto_vk

    pontos_alta = sum(v == 1 for v in componentes.values())
    pontos_baixa = sum(v == -1 for v in componentes.values())
    adx = float(u["adx"])
    vantagem = abs(pontos_alta - pontos_baixa)

    # Exige predominancia clara e ADX minimo. Caso contrario, nao inventa direcao.
    if adx >= ADX_LATERAL and pontos_alta >= 4 and vantagem >= 3:
        sinal, tendencia = "COMPRA", "ALTA"
        motivos = [k for k, v in componentes.items() if v == 1]
    elif adx >= ADX_LATERAL and pontos_baixa >= 4 and vantagem >= 3:
        sinal, tendencia = "VENDA", "BAIXA"
        motivos = [k for k, v in componentes.items() if v == -1]
    else:
        sinal = "AGUARDAR"
        tendencia = "LATERAL" if adx < ADX_LATERAL else "TRANSICAO"
        motivos = ["Predominancia insuficiente no grafico atual"]

    return {
        "sinal": sinal,
        "compra": int(pontos_alta),
        "venda": int(pontos_baixa),
        "vantagem": int(vantagem),
        "rompimento": "DESATIVADO",
        "tendencia": tendencia,
        "motivos": motivos,
        "contexto_1m": "NAO UTILIZADO",
        "contexto_5m": "NAO UTILIZADO",
        "componentes_tendencia": componentes,
        "vortex_kroll_estado": estado_vk,
        "vortex_plus": float(u["vortex_plus"]),
        "vortex_minus": float(u["vortex_minus"]),
        "kroll_superior": float(u["kroll_superior"]),
        "kroll_inferior": float(u["kroll_inferior"]),
        "adx": adx
    }

def prever_proximo_candlestick(df):
    """
    Estima a direcao do proximo candle fechado do timeframe atual (M1).
    Usa exclusivamente candles fechados e combina familias independentes.
    Percentual e score heuristico, nao probabilidade estatisticamente calibrada.
    """
    if len(df) < 220:
        return {"direcao": "INDEFINIDO", "confianca": 0, "alta": 0, "baixa": 0,
                "familias": {}, "motivos": ["Historico insuficiente"]}

    u = df.iloc[-1]
    p = df.iloc[-2]
    p2 = df.iloc[-3]
    votos = {}

    # 1) Tendencia e alinhamento de medias.
    votos["TENDENCIA_EMAS"] = (
        1 if u["ema3"] > u["ema13"] > u["ema30"] > u["ema60"] and u["close"] > u["ema200"]
        else (-1 if u["ema3"] < u["ema13"] < u["ema30"] < u["ema60"] and u["close"] < u["ema200"] else 0)
    )

    # 2) Forca direcional.
    votos["ADX_DI"] = (
        1 if u["adx"] >= ADX_LATERAL and u["di_plus"] > u["di_minus"]
        else (-1 if u["adx"] >= ADX_LATERAL and u["di_minus"] > u["di_plus"] else 0)
    )

    # 3) MACD: lado do histograma e aceleracao.
    votos["MACD"] = (
        1 if u["macd_hist"] > 0 and u["macd_hist"] >= p["macd_hist"]
        else (-1 if u["macd_hist"] < 0 and u["macd_hist"] <= p["macd_hist"] else 0)
    )

    # 4) Momentum / ROC.
    votos["MOMENTUM_ROC"] = (
        1 if u["close"] > p["close"] and u["roc"] > 0
        else (-1 if u["close"] < p["close"] and u["roc"] < 0 else 0)
    )

    # 5) RSI e estocastico, evitando usar sobrecompra/sobrevenda isoladamente.
    votos["RSI_ESTOCASTICO"] = (
        1 if u["rsi"] >= 52 and u["stoch_k"] >= u["stoch_d"] and u["stoch_k"] < 85
        else (-1 if u["rsi"] <= 48 and u["stoch_k"] <= u["stoch_d"] and u["stoch_k"] > 15 else 0)
    )

    # 6) Candlestick: corpo, fechamento e rejeicao das sombras.
    amplitude = max(float(u["high"] - u["low"]), 1e-12)
    corpo = float(u["close"] - u["open"])
    pos_fechamento = float((u["close"] - u["low"]) / amplitude)
    sombra_inf = float(min(u["open"], u["close"]) - u["low"])
    sombra_sup = float(u["high"] - max(u["open"], u["close"]))
    candle_vote = 0
    if bool(u.get("engolfo_alta", False)) or (corpo > 0 and pos_fechamento > 0.72 and abs(corpo) / amplitude > 0.55):
        candle_vote = 1
    elif bool(u.get("engolfo_baixa", False)) or (corpo < 0 and pos_fechamento < 0.28 and abs(corpo) / amplitude > 0.55):
        candle_vote = -1
    elif bool(u.get("martelo", False)) and pos_fechamento > 0.55:
        candle_vote = 1
    elif bool(u.get("estrela_cadente", False)) and pos_fechamento < 0.45:
        candle_vote = -1
    votos["CANDLESTICK"] = candle_vote

    # 7) Volatilidade / bandas: expansao com fechamento direcional.
    largura_bb = float(u["bb_superior"] - u["bb_inferior"])
    largura_ant = float(p["bb_superior"] - p["bb_inferior"])
    expandindo = largura_bb > largura_ant
    votos["VOLATILIDADE_BOLLINGER"] = (
        1 if expandindo and u["close"] > u["bb_media"] and u["close"] > p["close"]
        else (-1 if expandindo and u["close"] < u["bb_media"] and u["close"] < p["close"] else 0)
    )

    # 8) Estrutura curta: sequencia de fechamentos e rompimento da maxima/minima anterior.
    votos["ESTRUTURA"] = (
        1 if u["close"] > p["close"] > p2["close"] and u["high"] >= p["high"]
        else (-1 if u["close"] < p["close"] < p2["close"] and u["low"] <= p["low"] else 0)
    )

    # 9) CCI.
    votos["CCI"] = 1 if u["cci"] > 25 else (-1 if u["cci"] < -25 else 0)

    # Vortex + Kroll Stop contam como uma unica familia de confirmacao.
    voto_vk, _ = decisao_vortex_kroll(u)
    votos["VORTEX_KROLL"] = voto_vk

    # Ponderacao: familias de maior relevancia recebem peso maior.
    pesos = {
        "TENDENCIA_EMAS": 1.35, "ADX_DI": 1.15, "MACD": 1.15,
        "MOMENTUM_ROC": 1.0, "RSI_ESTOCASTICO": 0.85,
        "CANDLESTICK": 1.25, "VOLATILIDADE_BOLLINGER": 0.75,
        "ESTRUTURA": 1.15, "CCI": 0.75, "VORTEX_KROLL": 1.15
    }
    total = sum(pesos[k] for k in votos)
    score_alta = sum(pesos[k] for k, v in votos.items() if v == 1)
    score_baixa = sum(pesos[k] for k, v in votos.items() if v == -1)
    diferenca = score_alta - score_baixa
    intensidade = abs(diferenca) / total
    concordantes = sum(v == (1 if diferenca > 0 else -1) for v in votos.values()) if diferenca else 0

    # Limites conservadores: conflito ou baixa concordancia vira indefinido.
    if intensidade >= 0.22 and concordantes >= 5:
        direcao = "ALTA" if diferenca > 0 else "BAIXA"
        confianca = int(min(85, 50 + intensidade * 42 + max(0, concordantes - 5) * 2))
    else:
        direcao = "INDEFINIDO"
        confianca = int(max(0, 50 + intensidade * 20))

    motivos = [k for k, v in votos.items() if v == (1 if direcao == "ALTA" else -1)] if direcao != "INDEFINIDO" else [
        "Conflito entre familias ou concordancia insuficiente"
    ]
    proxima_abertura = int(u["timestamp"]) + INTERVALO_CANDLE
    return {
        "direcao": direcao, "confianca": confianca,
        "alta": round(score_alta, 2), "baixa": round(score_baixa, 2),
        "familias": votos, "motivos": motivos,
        "timestamp_proximo_candle": proxima_abertura,
        "hora_proximo_candle": formatar_hora(proxima_abertura, utc=False)
    }


def calcular_motor_quantitativo(df, info):
    """Resumo da forca da tendencia, sem sinais de outros periodos."""
    u = df.iloc[-1]
    lado = 1 if info["sinal"] == "COMPRA" else (-1 if info["sinal"] == "VENDA" else 0)
    componentes = info.get("componentes_tendencia", {})
    ativos = [v for v in componentes.values() if v != 0]
    alinhados = sum(1 for v in ativos if v == lado) if lado else 0
    concordancia = int(round(100 * alinhados / len(ativos))) if ativos and lado else 0
    alinhamento = sum(v == lado for v in componentes.values()) if lado else 0
    forca = int(round((alinhamento / max(1, len(componentes))) * 100))
    momentum = float((u["close"] - df.iloc[-7]["close"]) / u["atr"]) if u["atr"] > 0 else 0.0
    direcao = "ALTA" if lado > 0 else ("BAIXA" if lado < 0 else "INDEFINIDA")
    regime = "TENDENCIA" if info["sinal"] in ("COMPRA", "VENDA") else info["tendencia"]
    return {
        "direcao": direcao, "forca": forca, "regime": regime,
        "momentum": momentum, "concordancia": concordancia,
        "conflito": False, "componentes": componentes,
        "indice": lado * forca / 100.0, "incerteza": 100 - forca,
        "razao_volatilidade": 1.0, "votos_ativos": len(ativos)
    }

def avaliar_continuidade(df, sinal_atual, sinal_anterior):
    if sinal_atual == "AGUARDAR":
        return "SEM TENDENCIA PREDOMINANTE"
    u, anterior = df.iloc[-1], df.iloc[-2]
    if sinal_atual == "COMPRA":
        alinhado = (u["ema3"] > u["ema13"] > u["ema30"]
                    and u["di_plus"] > u["di_minus"]
                    and u["macd_hist"] > 0)
        impulso = u["close"] >= anterior["close"]
    else:
        alinhado = (u["ema3"] < u["ema13"] < u["ema30"]
                    and u["di_minus"] > u["di_plus"]
                    and u["macd_hist"] < 0)
        impulso = u["close"] <= anterior["close"]
    if not alinhado:
        return "EM RISCO"
    return "MANTIDO" if impulso else "ENFRAQUECENDO"

def calcular_suporte_resistencia(df):
    janela = df.tail(JANELA_SR)
    return {"suporte": float(janela["low"].min()), "resistencia": float(janela["high"].max())}


def calcular_projecoes(df, sinal):
    """Projeta cenarios direcionais de 5 e 15 minutos a partir de candles M1."""
    u = df.iloc[-1]
    preco, atr = float(u["close"]), float(u["atr"])
    if not np.isfinite(atr) or atr <= 0:
        raise ValueError("ATR invalido; projecoes interrompidas.")

    niveis_atr = {
        m: {"distancia_preco": float(atr * m),
            "compra": float(preco + atr * m),
            "venda": float(preco - atr * m)}
        for m in (1, 2, 3, 5)
    }
    if sinal not in ("COMPRA", "VENDA"):
        return {"atr": atr, "niveis_atr": niveis_atr, "alvo_curto": None,
                "alvo_longo": None, "detalhes": {}, "fibonacci": {}}

    direcao = 1 if sinal == "COMPRA" else -1
    detalhes = {}
    for minutos in HORIZONTES_MINUTOS:
        barras = (minutos * 60) // INTERVALO_CANDLE
        # Escala de volatilidade pela raiz do tempo; estimativa, nao alvo garantido.
        distancia = atr * math.sqrt(barras) * 0.45
        alvo = float(preco + direcao * distancia)
        detalhes[minutos] = {
            "preco": alvo,
            "distancia_preco": float(distancia),
            "distancia_atr": float(distancia / atr),
            "multiplo_atr_aproximado": round(float(distancia / atr), 2),
            "horizonte_minutos": minutos
        }

    return {
        "atr": atr, "niveis_atr": niveis_atr,
        "alvo_curto": detalhes.get(5, {}).get("preco"),
        "alvo_longo": detalhes.get(15, {}).get("preco"),
        "detalhes": detalhes, "fibonacci": {}
    }

def classificar_alvo(info, continuidade, projecoes, df):
    if info["sinal"] == "AGUARDAR":
        return "SEM ALVO — SEM TENDENCIA"
    if continuidade == "EM RISCO":
        return "PROJECAO SUSPENSA — TENDENCIA EM RISCO"
    return "PROJECAO DIRECIONAL 5M + 15M"

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
        "vortex_plus": float(u["vortex_plus"]), "vortex_minus": float(u["vortex_minus"]),
        "kroll_superior": float(u["kroll_superior"]), "kroll_inferior": float(u["kroll_inferior"]),
        "vortex_kroll_estado": info.get("vortex_kroll_estado", "INDISPONIVEL"),
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
    validar_ativo_otc(ativo)
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


def mostrar_painel(ativo, df, info, continuidade, tipo_alvo, projecoes, projecoes_horarias, previsao, falhas, coleta_ms=0.0, calculo_ms=0.0):
    """Painel exclusivo da tendencia predominante no timeframe atual."""
    u = df.iloc[-1]
    limpar_tela()
    sinal = info["sinal"]
    if sinal == "COMPRA":
        titulo, cor_tendencia = "TENDENCIA PREDOMINANTE: ALTA", "1;92"
    elif sinal == "VENDA":
        titulo, cor_tendencia = "TENDENCIA PREDOMINANTE: BAIXA", "1;91"
    else:
        titulo, cor_tendencia = "SEM TENDENCIA PREDOMINANTE", "1;93"

    motor = info.get("motor", {})
    print(cor("=" * 42, "96"))
    print(cor(" QMS QUANTUM FUTURE V5.3.7 OTC", "1;96"))
    print(cor(" TENDENCIA + PREVISAO M1 + PROJECAO 15M", "96"))
    print(cor("=" * 42, "96"))
    print(f"Ativo: {ativo} | Timeframe real da API: M1 ({INTERVALO_CANDLE}s)")
    print(f"Hora: {hora_local()} | Candle fechado: {u['hora_local']}")
    idade = max(0.0, time.time() - (int(u["timestamp"]) + INTERVALO_CANDLE))
    print(f"Latencia: coleta {coleta_ms:.0f} ms | calculo {calculo_ms:.0f} ms | idade {idade:.1f}s")
    print(cor(titulo, cor_tendencia))
    print(f"Forca da tendencia: {motor.get('forca', 0)}/100")
    print(f"ADX: {u['adx']:.1f} | DI+: {u['di_plus']:.1f} | DI-: {u['di_minus']:.1f}")
    print(f"Vortex(14): VI+ {u['vortex_plus']:.3f} | VI- {u['vortex_minus']:.3f}")
    print(f"Kroll Stop: superior {u['kroll_superior']:.6f} | inferior {u['kroll_inferior']:.6f}")
    print(f"Decisao Vortex + Kroll: {info.get('vortex_kroll_estado', 'INDISPONIVEL')}")
    print(f"EMA 3/13/30/60: {u['ema3']:.6f} / {u['ema13']:.6f} / {u['ema30']:.6f} / {u['ema60']:.6f}")
    print(f"EMA 200: {u['ema200']:.6f} | RSI: {u['rsi']:.1f}")
    print(f"MACD histograma: {u['macd_hist']:.8f}")
    print(f"Momentum: {motor.get('momentum', 0.0):+.2f} ATR")
    print(f"Concordancia interna: {motor.get('concordancia', 0)}%")
    print(cor("-" * 42, "90"))
    print(cor("PREVISAO M1 + PROJECAO 15M (M1)", "1;96"))
    print(f"Abertura estimada do candle previsto: {previsao.get('hora_proximo_candle', 'indisponivel')}")
    direcao_prev = previsao["direcao"]
    cor_prev = "1;92" if direcao_prev == "ALTA" else ("1;91" if direcao_prev == "BAIXA" else "1;93")
    print(cor(f"PROXIMO CANDLE: {direcao_prev}", cor_prev))
    print(f"Confianca heuristica: {previsao['confianca']}% | Score alta: {previsao['alta']} | Score baixa: {previsao['baixa']}")
    print("Familias: " + ", ".join(f"{k}={('+' if v > 0 else '-' if v < 0 else '0')}" for k, v in previsao["familias"].items()))
    print("A favor: " + ", ".join(previsao["motivos"]))
    print(cor("-" * 42, "90"))
    print(f"Estado: {continuidade} | {tipo_alvo}")
    print(cor("PROJECOES FOREX — 5 E 15 MINUTOS (BASE M1)", "1;96"))
    for horizonte in (5, 15):
        alvo = projecoes["detalhes"].get(horizonte)
        if alvo and sinal in ("COMPRA", "VENDA") and continuidade != "EM RISCO":
            sentido = "ACIMA" if sinal == "COMPRA" else "ABAIXO"
            print(f"Projecao {horizonte}M: {sentido} | preco estimado {alvo['preco']:.6f}")
            print(f"  Distancia: {alvo['distancia_atr']:.2f} ATR | deslocamento: {alvo['distancia_preco']:.6f}")
        else:
            print(f"Projecao {horizonte}M: INDEFINIDA / SUSPENSA")
    print("A previsao de 15M e uma estimativa de direcao e deslocamento, nao garantia de preco.")
    print(cor("-" * 42, "90"))
    if sinal == "AGUARDAR":
        print(cor("DECISAO: AGUARDAR — NAO FORCAR DIRECAO", "1;93"))
    elif continuidade == "EM RISCO":
        print(cor("DECISAO: TENDENCIA EM RISCO — PROJECAO SUSPENSA", "1;93"))
    else:
        print(cor(f"DECISAO: ACOMPANHAR SOMENTE {sinal}", cor_tendencia))
    print(f"Falhas: {falhas}/{MAX_FALHAS}")
    print(cor("SOMENTE LEITURA | SEM ORDENS | SEM MARTINGALE", "1;97"))
    print("Projecao e estimativa tecnica, nao garantia.")

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
            # Exige janela completa de candles de 1 minuto para validar.
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
    ativo = ATIVO_FIXO
    selecionar_ativo()  # informa o ativo fixo; nao oferece outro mercado
    api = conectar()
    falhas = 0
    ultimo_candle_processado = None
    ultimo_sinal_registrado = None
    ultimo_tipo_alvo_registrado = None
    sinal_anterior = None
    pendentes = []
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

            inicio_calculo = time.monotonic()
            df = adicionar_indicadores(candles)
            u = df.iloc[-1]
            criticas = ["ema3", "ema13", "ema21", "ema30", "ema50", "ema60", "ema200", "rsi", "atr", "adx", "di_plus", "di_minus", "macd", "macd_sinal", "macd_hist", "bb_media", "bb_superior", "bb_inferior", "stoch_k", "stoch_d", "cci", "roc", "vortex_plus", "vortex_minus", "kroll_superior", "kroll_inferior"]
            if any(pd.isna(u[c]) for c in criticas):
                raise ValueError("Indicadores incompletos no candle atual.")

            info = calcular_sinal(df)
            previsao = prever_proximo_candlestick(df)
            info["motor"] = calcular_motor_quantitativo(df, info)
            continuidade = avaliar_continuidade(df, info["sinal"], sinal_anterior)
            if continuidade == "EM RISCO":
                projecoes = calcular_projecoes(df, "AGUARDAR")
            else:
                projecoes = calcular_projecoes(df, info["sinal"])
            tipo_alvo = classificar_alvo(info, continuidade, projecoes, df)
            salvar_candles(ativo, candles)

            if info["sinal"] in ("COMPRA", "VENDA") and continuidade != "EM RISCO":
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
            mostrar_painel(ativo, df, info, continuidade, tipo_alvo, projecoes, None, previsao, falhas, coleta_ms, calculo_ms)
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
