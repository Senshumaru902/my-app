
# ============================================================
# QMS QUANTUM ANALYST V5.8 OTC
# PARTE 1/6 — CONFIGURAÇÃO E INDICADORES
# Somente análise; sem ordens automáticas; sem Martingale.
# ============================================================

import os
import sys
import time
import math
import csv
import getpass
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None


# ---------------- CONFIGURAÇÃO ----------------

VERSAO = "QMS QUANTUM ANALYST V5.8 OTC"

INTERVALO = 10
QUANTIDADE_CANDLES = 400
MINIMO_CANDLES = 220

TF_CONTEXTO_SEGUNDOS = 3600
CANDLES_CONTEXTO = 240
MINIMO_CANDLES_CONTEXTO = 220

INTERVALO_LOOP = 1
MAX_FALHAS_CONSECUTIVAS = 12
COOLDOWN_SINAL_SEGUNDOS = 60

ADX_MINIMO_CURTO = 16.0
ADX_ALVO_LONGO = 18.0

SCORE_MINIMO_CURTO = 5
SCORE_MINIMO_LONGO = 5
SCORE_MINIMO_HORAS = 5

PERIODO_RSI = 14
PERIODO_ATR = 14
PERIODO_ADX = 14

EMA_RAPIDA = 3
EMA_MEDIA = 30
EMA_TENDENCIA = 60
EMA_LONGA = 200

MACD_RAPIDA = 12
MACD_LENTA = 26
MACD_SINAL = 9

MOMENTUM_PERIODO = 10

JANELA_MICRO = 5
JANELA_ESTRUTURA_LONGA = 180
JANELA_EXTREMA_LONGA = 300

ALVO_CURTO_ATR_MIN = 0.8
ALVO_CURTO_ATR_MAX = 2.0
ALVO_LONGO_MIN_ATR = 3.0

FIBONACCI_NIVEIS = (1.272, 1.618, 2.000)
LADO_PIVOT = 3
MAX_ESTICAMENTO_ATR = 1.50
HORIZONTE_HORAS = 2

ARQUIVO_HISTORICO = "qms_v58_historico.csv"
ARQUIVO_ALVOS = "qms_v58_alvos.csv"

MODO_ANALISE = "AMBOS"
ATIVO = "EURUSD-OTC"

ULTIMO_SINAL = {}
FALHAS_CONSECUTIVAS = 0

# ---------------- CORES ----------------

RESET = "\033[0m"
VERDE = "\033[92m"
VERMELHO = "\033[91m"
AMARELO = "\033[93m"
AZUL = "\033[94m"
CIANO = "\033[96m"
MAGENTA = "\033[95m"
CINZA = "\033[90m"
NEGRITO = "\033[1m"


def colorir(texto, cor):
    return f"{cor}{texto}{RESET}"


def limpar_tela():
    os.system("clear")


def agora_texto():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def numero_valido(valor):
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError, OverflowError):
        return False


def valor_float(valor, padrao=np.nan):
    try:
        n = float(valor)
        return n if math.isfinite(n) else padrao
    except (TypeError, ValueError, OverflowError):
        return padrao


def dividir_seguro(a, b, padrao=0.0):
    if not numero_valido(a) or not numero_valido(b):
        return padrao
    if abs(float(b)) < 1e-12:
        return padrao
    r = float(a) / float(b)
    return r if math.isfinite(r) else padrao


# ---------------- SELEÇÃO ----------------

def selecionar_ativo():
    print("\nATIVO")
    print("1 - EURUSD")
    print("2 - EURUSD-OTC")
    print("3 - Outro ativo")

    escolha = input("Opção: ").strip()

    if escolha == "1":
        return "EURUSD"
    if escolha == "2":
        return "EURUSD-OTC"
    if escolha == "3":
        nome = input("Nome exato do ativo: ").strip()
        if nome:
            return nome

    return "EURUSD-OTC"


def selecionar_modo():
    print("\nMODO DE ANÁLISE")
    print("1 - Somente COMPRA / CALL")
    print("2 - Somente VENDA / PUT")
    print("3 - COMPRA e VENDA")

    escolha = input("Opção: ").strip()

    if escolha == "1":
        return "COMPRA"
    if escolha == "2":
        return "VENDA"
    return "AMBOS"


def direcao_permitida(direcao):
    if direcao not in ("COMPRA", "VENDA"):
        return False
    return MODO_ANALISE == "AMBOS" or MODO_ANALISE == direcao


# ---------------- CONEXÃO ----------------

def conectar_iq():
    if IQ_Option is None:
        raise RuntimeError(
            "iqoptionapi ausente. Execute: pip install iqoptionapi"
        )

    email = input("E-mail da IQ Option: ").strip()
    senha = getpass.getpass("Senha da IQ Option: ")

    if not email or not senha:
        raise RuntimeError("Credenciais não informadas.")

    api = IQ_Option(email, senha)
    resultado = api.connect()

    if isinstance(resultado, tuple):
        conectado = bool(resultado[0])
        detalhe = resultado[1] if len(resultado) > 1 else ""
    else:
        conectado = bool(resultado)
        detalhe = ""

    if not conectado:
        raise RuntimeError(f"Falha na conexão: {detalhe}")

    print(colorir("Conexão estabelecida.", VERDE))
    return api


# ---------------- EMA ----------------

def calcular_ema(serie, periodo):
    serie = pd.Series(serie, dtype="float64")
    return serie.ewm(
        span=periodo,
        adjust=False,
        min_periods=periodo
    ).mean()


# ---------------- RSI ----------------

def calcular_rsi(fechamentos, periodo=14):
    close = pd.Series(fechamentos, dtype="float64")
    delta = close.diff()

    ganhos = delta.clip(lower=0)
    perdas = -delta.clip(upper=0)

    media_ganhos = ganhos.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    media_perdas = perdas.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    rs = media_ganhos / media_perdas.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask(
        (media_perdas == 0) & (media_ganhos > 0), 100.0
    )
    rsi = rsi.mask(
        (media_ganhos == 0) & (media_perdas > 0), 0.0
    )
    rsi = rsi.mask(
        (media_ganhos == 0) & (media_perdas == 0), 50.0
    )

    return rsi


# ---------------- ATR ----------------

def calcular_atr(df, periodo=14):
    high = df["max"]
    low = df["min"]
    close = df["close"]
    anterior = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - anterior).abs(),
            (low - anterior).abs()
        ],
        axis=1
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()


# ---------------- ADX / DMI ----------------

def calcular_adx(df, periodo=14):
    high = df["max"]
    low = df["min"]
    close = df["close"]

    movimento_alta = high.diff()
    movimento_baixa = -low.diff()

    plus_dm = movimento_alta.where(
        (movimento_alta > movimento_baixa) &
        (movimento_alta > 0), 0.0
    )

    minus_dm = movimento_baixa.where(
        (movimento_baixa > movimento_alta) &
        (movimento_baixa > 0), 0.0
    )

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ],
        axis=1
    ).max(axis=1)

    atr_suavizado = tr.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    plus_suave = plus_dm.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    minus_suave = minus_dm.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    plus_di = 100 * plus_suave / atr_suavizado.replace(0, np.nan)
    minus_di = 100 * minus_suave / atr_suavizado.replace(0, np.nan)

    soma = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / soma

    adx = dx.ewm(
        alpha=1 / periodo,
        adjust=False,
        min_periods=periodo
    ).mean()

    return adx, plus_di, minus_di


# ---------------- MACD ----------------

def calcular_macd(fechamentos):
    close = pd.Series(fechamentos, dtype="float64")

    ema_rapida = close.ewm(
        span=MACD_RAPIDA, adjust=False,
        min_periods=MACD_RAPIDA
    ).mean()

    ema_lenta = close.ewm(
        span=MACD_LENTA, adjust=False,
        min_periods=MACD_LENTA
    ).mean()

    linha = ema_rapida - ema_lenta
    sinal = linha.ewm(
        span=MACD_SINAL, adjust=False,
        min_periods=MACD_SINAL
    ).mean()

    histograma = linha - sinal
    return linha, sinal, histograma


# ---------------- MOMENTUM ----------------

def calcular_momentum(fechamentos, periodo=MOMENTUM_PERIODO):
    """
    Momentum absoluto:
        close atual - close de N candles atrás.

    Momentum percentual:
        (close atual / close de N candles atrás - 1) * 100.

    O Momentum ATR-normalizado permite comparar o deslocamento
    do preço com a volatilidade observada. Não é uma probabilidade.
    """
    close = pd.Series(fechamentos, dtype="float64")
    referencia = close.shift(periodo)

    absoluto = close - referencia
    percentual = (
        (close / referencia.replace(0, np.nan)) - 1
    ) * 100

    return absoluto, percentual


def classificar_momentum(valor, atr):
    if not numero_valido(valor) or not numero_valido(atr):
        return "INDISPONÍVEL", 0.0

    atr = float(atr)
    if atr <= 0:
        return "INDISPONÍVEL", 0.0

    normalizado = float(valor) / atr

    if normalizado >= 0.25:
        return "POSITIVO", normalizado
    if normalizado <= -0.25:
        return "NEGATIVO", normalizado

    return "NEUTRO", normalizado


# ---------------- INDICADORES INTEGRADOS ----------------

def calcular_indicadores(df):
    if len(df) < MINIMO_CANDLES:
        raise ValueError(
            f"Candles insuficientes: {len(df)}; "
            f"mínimo exigido: {MINIMO_CANDLES}"
        )

    resultado = df.copy()

    for periodo in (
        EMA_RAPIDA, EMA_MEDIA, EMA_TENDENCIA, EMA_LONGA
    ):
        resultado[f"ema_{periodo}"] = calcular_ema(
            resultado["close"], periodo
        )

    resultado["rsi"] = calcular_rsi(
        resultado["close"], PERIODO_RSI
    )

    resultado["atr"] = calcular_atr(
        resultado, PERIODO_ATR
    )

    adx, plus_di, minus_di = calcular_adx(
        resultado, PERIODO_ADX
    )
    resultado["adx"] = adx
    resultado["plus_di"] = plus_di
    resultado["minus_di"] = minus_di

    macd, macd_sinal, macd_hist = calcular_macd(
        resultado["close"]
    )
    resultado["macd"] = macd
    resultado["macd_sinal"] = macd_sinal
    resultado["macd_hist"] = macd_hist

    mom_abs, mom_pct = calcular_momentum(
        resultado["close"], MOMENTUM_PERIODO
    )
    resultado["momentum"] = mom_abs
    resultado["momentum_pct"] = mom_pct

    resultado["momentum_atr"] = (
        resultado["momentum"] /
        resultado["atr"].replace(0, np.nan)
    )

    return resultado

# ============================================================
# PARTE 2/6 — COLETA E VALIDAÇÃO DE DADOS
# ============================================================

def obter_candles(api, ativo, intervalo, quantidade):
    agora = int(time.time())

    dados = api.get_candles(
        ativo,
        intervalo,
        quantidade,
        agora
    )

    if not dados or not isinstance(dados, (list, tuple)):
        raise ValueError("API não retornou candles válidos.")

    df = pd.DataFrame(dados)

    obrigatorias = {"open", "close", "min", "max"}
    faltantes = obrigatorias - set(df.columns)

    if faltantes:
        raise ValueError(
            f"Campos ausentes nos candles: {sorted(faltantes)}"
        )

    if "from" not in df.columns:
        raise ValueError("API não forneceu horário inicial dos candles.")

    if "to" not in df.columns:
        raise ValueError("API não forneceu horário final dos candles.")

    colunas_numericas = ["open", "close", "min", "max", "from", "to"]

    for coluna in colunas_numericas:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=colunas_numericas)

    # Somente candles cujo horário final já passou.
    agora_float = time.time()
    df = df[df["to"] < agora_float].copy()

    df = df.sort_values("from")
    df = df.drop_duplicates(subset=["from"], keep="last")

    if len(df) < MINIMO_CANDLES:
        raise ValueError(
            f"Somente {len(df)} candles fechados válidos; "
            f"mínimo exigido: {MINIMO_CANDLES}."
        )

    precos = df[["open", "close", "min", "max"]].to_numpy(
        dtype=float
    )

    if not np.isfinite(precos).all():
        raise ValueError("Existem preços não finitos.")

    if (precos <= 0).any():
        raise ValueError("Foram encontrados preços não positivos.")

    # Consistência OHLC.
    incoerente = (
        (df["min"] > df["max"]) |
        (df["open"] < df["min"]) |
        (df["open"] > df["max"]) |
        (df["close"] < df["min"]) |
        (df["close"] > df["max"])
    )

    if incoerente.any():
        raise ValueError("Candles com OHLC inconsistente.")

    # Confere a regularidade dos últimos 30 candles.
    recentes = df.tail(30)
    diferencas = recentes["from"].diff().dropna()

    if len(diferencas) > 0:
        intervalos_validos = np.isclose(
            diferencas.to_numpy(dtype=float),
            float(intervalo),
            rtol=0,
            atol=1.5
        )

        if not intervalos_validos.all():
            raise ValueError(
                "Intervalo dos candles inconsistente. "
                "A API pode não fornecer candles nativos "
                "nesse timeframe."
            )

    df = df.reset_index(drop=True)

    return df


def obter_candles_contexto(api, ativo):
    return obter_candles(
        api,
        ativo,
        TF_CONTEXTO_SEGUNDOS,
        CANDLES_CONTEXTO
    )


def salvar_csv(caminho, dados):
    df = pd.DataFrame([dados])
    existe = os.path.exists(caminho)

    df.to_csv(
        caminho,
        mode="a",
        header=not existe,
        index=False,
        encoding="utf-8"
    )


def obter_ultimo_registro(df):
    if df is None or df.empty:
        raise ValueError("DataFrame sem registros.")

    registro = df.iloc[-1].to_dict()

    for chave, valor in registro.items():
        if isinstance(valor, np.generic):
            registro[chave] = valor.item()

    return registro

# ============================================================
# PARTE 3/6 — MICROESTRUTURA E ALVO CURTO
# ============================================================

def detectar_padrao_candle(df):
    if len(df) < 3:
        return "SEM DADOS"

    a = df.iloc[-2]
    b = df.iloc[-1]

    corpo = abs(float(b["close"]) - float(b["open"]))
    amplitude = float(b["max"]) - float(b["min"])

    if amplitude <= 0:
        return "INDEFINIDO"

    corpo_rel = corpo / amplitude
    pavio_sup = float(b["max"]) - max(
        float(b["open"]), float(b["close"])
    )
    pavio_inf = min(
        float(b["open"]), float(b["close"])
    ) - float(b["min"])

    alta_anterior = a["close"] > a["open"]
    baixa_anterior = a["close"] < a["open"]
    alta_atual = b["close"] > b["open"]
    baixa_atual = b["close"] < b["open"]

    if (
        baixa_anterior and alta_atual
        and b["open"] <= a["close"]
        and b["close"] >= a["open"]
    ):
        return "ENGOLFO DE ALTA"

    if (
        alta_anterior and baixa_atual
        and b["open"] >= a["close"]
        and b["close"] <= a["open"]
    ):
        return "ENGOLFO DE BAIXA"

    if corpo_rel <= 0.10:
        return "DOJI"

    if pavio_inf >= corpo * 2 and pavio_sup <= corpo:
        return "POSSÍVEL REJEIÇÃO DE BAIXA"

    if pavio_sup >= corpo * 2 and pavio_inf <= corpo:
        return "POSSÍVEL REJEIÇÃO DE ALTA"

    if corpo_rel >= 0.70:
        if alta_atual:
            return "CANDLE FORTE DE ALTA"
        if baixa_atual:
            return "CANDLE FORTE DE BAIXA"

    return "SEM PADRÃO FORTE"


def analisar_microestrutura(df):
    atual = df.iloc[-1]
    anterior = df.iloc[-2]
    janela = df.tail(JANELA_MICRO + 1).iloc[:-1]

    topo_anterior = float(janela["max"].max())
    fundo_anterior = float(janela["min"].min())

    close = float(atual["close"])
    ema3 = float(atual[f"ema_{EMA_RAPIDA}"])
    ema30 = float(atual[f"ema_{EMA_MEDIA}"])
    ema60 = float(atual[f"ema_{EMA_TENDENCIA}"])
    ema200 = float(atual[f"ema_{EMA_LONGA}"])

    if ema3 > ema30 and ema30 > ema60:
        micro = "ALTA"
    elif ema3 < ema30 and ema30 < ema60:
        micro = "BAIXA"
    else:
        micro = "LATERAL"

    if close > ema60 and ema60 > ema200:
        tendencia = "ALTA"
    elif close < ema60 and ema60 < ema200:
        tendencia = "BAIXA"
    else:
        tendencia = "MISTA"

    rompimento = "NENHUM"

    if close > topo_anterior:
        rompimento = "ALTA"
    elif close < fundo_anterior:
        rompimento = "BAIXA"

    reteste = False
    atr = valor_float(atual["atr"])

    if numero_valido(atr) and atr > 0:
        margem = atr * 0.20

        if rompimento == "ALTA":
            reteste = (
                abs(float(atual["min"]) - topo_anterior) <= margem
                and close > topo_anterior
            )
        elif rompimento == "BAIXA":
            reteste = (
                abs(float(atual["max"]) - fundo_anterior) <= margem
                and close < fundo_anterior
            )

    return {
        "microtendencia": micro,
        "tendencia": tendencia,
        "rompimento": rompimento,
        "reteste": reteste,
        "topo_micro": topo_anterior,
        "fundo_micro": fundo_anterior,
        "padrao": detectar_padrao_candle(df)
    }


def pontuar_alvo_curto(df, estrutura):
    atual = df.iloc[-1]

    close = valor_float(atual["close"])
    atr = valor_float(atual["atr"])
    rsi = valor_float(atual["rsi"])
    adx = valor_float(atual["adx"])
    plus_di = valor_float(atual["plus_di"])
    minus_di = valor_float(atual["minus_di"])
    macd_hist = valor_float(atual["macd_hist"])
    momentum = valor_float(atual["momentum"])
    momentum_atr = valor_float(atual["momentum_atr"])

    score_compra = 0
    score_venda = 0
    motivos_compra = []
    motivos_venda = []

    if not all(numero_valido(v) for v in [
        close, atr, rsi, adx, plus_di, minus_di,
        macd_hist, momentum, momentum_atr
    ]):
        return {
            "status": "AGUARDANDO",
            "direcao": "NEUTRO",
            "score_compra": 0,
            "score_venda": 0,
            "motivos_compra": [],
            "motivos_venda": [],
            "alvo": np.nan,
            "momentum_atr": np.nan
        }

    if atr <= 0:
        return {
            "status": "AGUARDANDO",
            "direcao": "NEUTRO",
            "score_compra": 0,
            "score_venda": 0,
            "motivos_compra": [],
            "motivos_venda": [],
            "alvo": np.nan,
            "momentum_atr": np.nan
        }

    ema3 = float(atual[f"ema_{EMA_RAPIDA}"])
    ema30 = float(atual[f"ema_{EMA_MEDIA}"])
    ema60 = float(atual[f"ema_{EMA_TENDENCIA}"])

    if ema3 > ema30:
        score_compra += 1
        motivos_compra.append("EMA3 acima EMA30")
    elif ema3 < ema30:
        score_venda += 1
        motivos_venda.append("EMA3 abaixo EMA30")

    if estrutura["microtendencia"] == "ALTA":
        score_compra += 1
        motivos_compra.append("Microtendência de alta")
    elif estrutura["microtendencia"] == "BAIXA":
        score_venda += 1
        motivos_venda.append("Microtendência de baixa")

    if estrutura["tendencia"] == "ALTA":
        score_compra += 1
        motivos_compra.append("Tendência principal de alta")
    elif estrutura["tendencia"] == "BAIXA":
        score_venda += 1
        motivos_venda.append("Tendência principal de baixa")

    if rsi >= 52:
        score_compra += 1
        motivos_compra.append("RSI favorece alta")
    elif rsi <= 48:
        score_venda += 1
        motivos_venda.append("RSI favorece baixa")

    if adx >= ADX_MINIMO_CURTO:
        if plus_di > minus_di:
            score_compra += 1
            motivos_compra.append("DMI favorece compradores")
        elif minus_di > plus_di:
            score_venda += 1
            motivos_venda.append("DMI favorece vendedores")

    if macd_hist > 0:
        score_compra += 1
        motivos_compra.append("MACD positivo")
    elif macd_hist < 0:
        score_venda += 1
        motivos_venda.append("MACD negativo")

    # Momentum participa da pontuação.
    # Exige deslocamento mínimo de 0,25 ATR.
    if momentum_atr >= 0.25:
        score_compra += 1
        motivos_compra.append(
            f"Momentum positivo ({momentum_atr:.2f} ATR)"
        )
    elif momentum_atr <= -0.25:
        score_venda += 1
        motivos_venda.append(
            f"Momentum negativo ({momentum_atr:.2f} ATR)"
        )

    if estrutura["rompimento"] == "ALTA":
        score_compra += 1
        motivos_compra.append("Rompimento de microtopo")
    elif estrutura["rompimento"] == "BAIXA":
        score_venda += 1
        motivos_venda.append("Rompimento de microfundo")

    if estrutura["reteste"]:
        if estrutura["rompimento"] == "ALTA":
            score_compra += 1
            motivos_compra.append("Reteste do rompimento de alta")
        elif estrutura["rompimento"] == "BAIXA":
            score_venda += 1
            motivos_venda.append("Reteste do rompimento de baixa")

    padrao = estrutura["padrao"]

    if padrao in (
        "ENGOLFO DE ALTA", "CANDLE FORTE DE ALTA",
        "POSSÍVEL REJEIÇÃO DE BAIXA"
    ):
        score_compra += 1
        motivos_compra.append(padrao)

    if padrao in (
        "ENGOLFO DE BAIXA", "CANDLE FORTE DE BAIXA",
        "POSSÍVEL REJEIÇÃO DE ALTA"
    ):
        score_venda += 1
        motivos_venda.append(padrao)

    # Evita comprar ou vender após extensão excessiva.
    distancia_atr = abs(close - ema30) / atr
    esticado = distancia_atr > MAX_ESTICAMENTO_ATR

    direcao = "NEUTRO"
    status = "AGUARDANDO"
    alvo = np.nan

    compra_ok = (
        score_compra >= SCORE_MINIMO_CURTO
        and score_compra >= score_venda + 2
        and estrutura["microtendencia"] == "ALTA"
        and estrutura["tendencia"] == "ALTA"
        and adx >= ADX_MINIMO_CURTO
        and not esticado
    )

    venda_ok = (
        score_venda >= SCORE_MINIMO_CURTO
        and score_venda >= score_compra + 2
        and estrutura["microtendencia"] == "BAIXA"
        and estrutura["tendencia"] == "BAIXA"
        and adx >= ADX_MINIMO_CURTO
        and not esticado
    )

    if compra_ok and direcao_permitida("COMPRA"):
        direcao = "COMPRA"
        status = "CANDIDATO"
        alvo = close + atr * ALVO_CURTO_ATR_MAX

    elif venda_ok and direcao_permitida("VENDA"):
        direcao = "VENDA"
        status = "CANDIDATO"
        alvo = close - atr * ALVO_CURTO_ATR_MAX

    return {
        "status": status,
        "direcao": direcao,
        "score_compra": score_compra,
        "score_venda": score_venda,
        "motivos_compra": motivos_compra,
        "motivos_venda": motivos_venda,
        "alvo": alvo,
        "esticado": esticado,
        "distancia_atr": distancia_atr,
        "momentum_atr": momentum_atr
    }

# ============================================================
# PARTE 4/6 — ALVOS LONGOS E CONTEXTO DE HORAS
# ============================================================

def detectar_pivos(df, lado=LADO_PIVOT):
    topos = []
    fundos = []

    if len(df) < lado * 2 + 1:
        return topos, fundos

    for i in range(lado, len(df) - lado):
        maximo = float(df["max"].iloc[i])
        minimo = float(df["min"].iloc[i])

        janela_max = df["max"].iloc[i-lado:i+lado+1]
        janela_min = df["min"].iloc[i-lado:i+lado+1]

        if maximo >= float(janela_max.max()):
            if int((janela_max == maximo).sum()) == 1:
                topos.append((i, maximo))

        if minimo <= float(janela_min.min()):
            if int((janela_min == minimo).sum()) == 1:
                fundos.append((i, minimo))

    return topos, fundos


def projetar_alvo_longo(df):
    atual = df.iloc[-1]
    preco = valor_float(atual["close"])
    atr = valor_float(atual["atr"])

    resultado = {
        "status": "SEM PROJEÇÃO",
        "direcao": "NEUTRO",
        "alvo_1": np.nan,
        "alvo_2": np.nan,
        "alvo_3": np.nan,
        "topo_estrutura": np.nan,
        "fundo_estrutura": np.nan,
        "score_compra": 0,
        "score_venda": 0,
        "momentum_atr": np.nan
    }

    if not numero_valido(preco) or not numero_valido(atr) or atr <= 0:
        return resultado

    janela = df.tail(min(
        len(df), JANELA_EXTREMA_LONGA
    )).copy()

    topos, fundos = detectar_pivos(janela)

    topo = float(janela["max"].max())
    fundo = float(janela["min"].min())

    resultado["topo_estrutura"] = topo
    resultado["fundo_estrutura"] = fundo

    if not topos or not fundos:
        resultado["status"] = "PIVÔS INSUFICIENTES"
        return resultado

    ema30 = valor_float(atual[f"ema_{EMA_MEDIA}"])
    ema60 = valor_float(atual[f"ema_{EMA_TENDENCIA}"])
    ema200 = valor_float(atual[f"ema_{EMA_LONGA}"])
    adx = valor_float(atual["adx"])
    plus_di = valor_float(atual["plus_di"])
    minus_di = valor_float(atual["minus_di"])
    momentum_atr = valor_float(atual["momentum_atr"])

    if not all(numero_valido(x) for x in [
        ema30, ema60, ema200, adx, plus_di,
        minus_di, momentum_atr
    ]):
        resultado["status"] = "INDICADORES INSUFICIENTES"
        return resultado

    score_compra = 0
    score_venda = 0

    if preco > ema60 > ema200:
        score_compra += 2
    if preco < ema60 < ema200:
        score_venda += 2

    if ema30 > ema60:
        score_compra += 1
    elif ema30 < ema60:
        score_venda += 1

    if adx >= ADX_ALVO_LONGO:
        if plus_di > minus_di:
            score_compra += 1
        elif minus_di > plus_di:
            score_venda += 1

    if momentum_atr >= 0.25:
        score_compra += 1
    elif momentum_atr <= -0.25:
        score_venda += 1

    resultado["score_compra"] = score_compra
    resultado["score_venda"] = score_venda
    resultado["momentum_atr"] = momentum_atr

    amplitude = topo - fundo

    if amplitude <= 0:
        resultado["status"] = "ESTRUTURA INVÁLIDA"
        return resultado

    if score_compra >= SCORE_MINIMO_LONGO and score_compra > score_venda:
        direcao = "COMPRA"
        # A projeção usa o extremo superior observado como referência.
        base = max(fundo, preco - amplitude)
        alvos = [
            topo + amplitude * (nivel - 1.0)
            for nivel in FIBONACCI_NIVEIS
        ]

        # Evita apresentar alvos abaixo do preço atual.
        alvos = [x for x in alvos if x > preco]

    elif score_venda >= SCORE_MINIMO_LONGO and score_venda > score_compra:
        direcao = "VENDA"
        alvos = [
            fundo - amplitude * (nivel - 1.0)
            for nivel in FIBONACCI_NIVEIS
        ]
        alvos = [x for x in alvos if x < preco]

    else:
        resultado["status"] = "CONFLUÊNCIA LONGA INSUFICIENTE"
        return resultado

    if not alvos:
        resultado["status"] = "ALVO NÃO CONFIRMADO"
        return resultado

    if abs(alvos[0] - preco) < ALVO_LONGO_MIN_ATR * atr:
        resultado["status"] = "ALVO PRÓXIMO DEMAIS"
        return resultado

    if not direcao_permitida(direcao):
        resultado["status"] = "BLOQUEADO PELO MODO"
        return resultado

    resultado.update({
        "status": "PROJEÇÃO TÉCNICA - NÃO GARANTIDA",
        "direcao": direcao,
        "alvo_1": alvos[0],
        "alvo_2": alvos[1] if len(alvos) > 1 else np.nan,
        "alvo_3": alvos[2] if len(alvos) > 2 else np.nan
    })

    return resultado


def analisar_contexto_horas(df_horas):
    atual = df_horas.iloc[-1]

    campos = [
        "close", "atr", "adx", "plus_di",
        "minus_di", "macd_hist", "momentum_atr"
    ]

    if any(not numero_valido(atual.get(c, np.nan)) for c in campos):
        return {
            "status": "CONTEXTO INDISPONÍVEL",
            "direcao": "NEUTRO",
            "score_compra": 0,
            "score_venda": 0
        }

    preco = float(atual["close"])
    ema60 = valor_float(atual.get("ema_60"))
    ema200 = valor_float(atual.get("ema_200"))
    adx = float(atual["adx"])
    plus_di = float(atual["plus_di"])
    minus_di = float(atual["minus_di"])
    macd_hist = float(atual["macd_hist"])
    momentum_atr = float(atual["momentum_atr"])

    if not numero_valido(ema60) or not numero_valido(ema200):
        return {
            "status": "CONTEXTO INDISPONÍVEL",
            "direcao": "NEUTRO",
            "score_compra": 0,
            "score_venda": 0
        }

    compra = 0
    venda = 0

    if preco > ema60 > ema200:
        compra += 2
    elif preco < ema60 < ema200:
        venda += 2

    if adx >= ADX_ALVO_LONGO:
        if plus_di > minus_di:
            compra += 1
        elif minus_di > plus_di:
            venda += 1

    if macd_hist > 0:
        compra += 1
    elif macd_hist < 0:
        venda += 1

    # Momentum no timeframe de uma hora.
    if momentum_atr >= 0.25:
        compra += 1
    elif momentum_atr <= -0.25:
        venda += 1

    direcao = "NEUTRO"
    status = "CONTEXTO MISTO"

    if compra >= SCORE_MINIMO_HORAS and compra > venda:
        direcao = "COMPRA"
        status = "CONTEXTO DE ALTA"
    elif venda >= SCORE_MINIMO_HORAS and venda > compra:
        direcao = "VENDA"
        status = "CONTEXTO DE BAIXA"

    return {
        "status": status,
        "direcao": direcao,
        "score_compra": compra,
        "score_venda": venda,
        "momentum_atr": momentum_atr
    }

# ============================================================
# PARTE 5/6 — CONFLUÊNCIA, PAINEL E HISTÓRICO
# ============================================================

def avaliar_confluencia(curto, longo, horas):
    direcao_curta = curto.get("direcao", "NEUTRO")
    direcao_longa = longo.get("direcao", "NEUTRO")
    direcao_horas = horas.get("direcao", "NEUTRO")

    if curto.get("status") != "CANDIDATO":
        return {
            "status": "AGUARDANDO SINAL CURTO",
            "direcao": "NEUTRO"
        }

    direcao = direcao_curta
    concordancias = 0

    if direcao_longa == direcao:
        concordancias += 1

    if direcao_horas == direcao:
        concordancias += 1

    if concordancias == 2:
        status = "CONFLUÊNCIA 3 MÓDULOS"
    elif concordancias == 1:
        status = "CONFLUÊNCIA PARCIAL"
    else:
        status = "SINAL CURTO SEM CONFIRMAÇÃO DOS OUTROS MÓDULOS"

    return {
        "status": status,
        "direcao": direcao,
        "concordancias": concordancias
    }


def formatar_preco(valor):
    if not numero_valido(valor):
        return "--"
    return f"{float(valor):.6f}"


def formatar_atr(valor):
    if not numero_valido(valor):
        return "--"
    # Exibe o valor real, sem arredondar para inteiro.
    return f"{float(valor):.6f}"


def formatar_numero(valor, casas=2):
    if not numero_valido(valor):
        return "--"
    return f"{float(valor):.{casas}f}"


def emitir_painel(df, curto, longo, horas, confluencia):
    atual = df.iloc[-1]
    estrutura = analisar_microestrutura(df)

    limpar_tela()

    print(colorir("=" * 58, CIANO))
    print(colorir(VERSAO, NEGRITO))
    print(colorir("=" * 58, CIANO))

    print(f"Horário: {agora_texto()}")
    print(f"Ativo: {ATIVO} | Modo: {MODO_ANALISE}")
    print(f"Preço: {formatar_preco(atual['close'])}")
    print(f"ATR: {formatar_atr(atual['atr'])}")
    print(f"RSI: {formatar_numero(atual['rsi'])}")
    print(f"ADX: {formatar_numero(atual['adx'])}")
    print(f"+DI: {formatar_numero(atual['plus_di'])}")
    print(f"-DI: {formatar_numero(atual['minus_di'])}")

    print("\n--- TENDÊNCIA E MOMENTUM ---")
    print(f"Tendência: {estrutura['tendencia']}")
    print(f"Microtendência: {estrutura['microtendencia']}")
    print(f"Rompimento: {estrutura['rompimento']}")
    print(f"Reteste: {'SIM' if estrutura['reteste'] else 'NÃO'}")
    print(f"Padrão: {estrutura['padrao']}")
    print(f"Momentum absoluto: {formatar_preco(atual['momentum'])}")
    print(f"Momentum percentual: {formatar_numero(atual['momentum_pct'], 4)}%")
    print(f"Momentum / ATR: {formatar_numero(atual['momentum_atr'])}")

    print("\n--- MÓDULO CURTO ---")
    print(f"Estado: {curto['status']}")
    print(f"Direção: {curto['direcao']}")
    print(
        f"Score COMPRA: {curto['score_compra']} | "
        f"Score VENDA: {curto['score_venda']}"
    )
    print(f"Alvo curto estimado: {formatar_preco(curto['alvo'])}")

    if curto.get("motivos_compra"):
        print("Critérios compra: " + "; ".join(curto["motivos_compra"]))

    if curto.get("motivos_venda"):
        print("Critérios venda: " + "; ".join(curto["motivos_venda"]))

    print("\n--- MÓDULO LONGO ---")
    print(f"Estado: {longo['status']}")
    print(f"Direção projetada: {longo['direcao']}")
    print(f"Topo estrutural: {formatar_preco(longo['topo_estrutura'])}")
    print(f"Fundo estrutural: {formatar_preco(longo['fundo_estrutura'])}")
    print(f"Alvo 1: {formatar_preco(longo['alvo_1'])}")
    print(f"Alvo 2: {formatar_preco(longo['alvo_2'])}")
    print(f"Alvo 3: {formatar_preco(longo['alvo_3'])}")

    print("\n--- CONTEXTO DE HORAS ---")
    print(f"Estado: {horas['status']}")
    print(f"Direção: {horas['direcao']}")
    print(
        f"Score COMPRA: {horas['score_compra']} | "
        f"Score VENDA: {horas['score_venda']}"
    )

    print("\n--- CONFLUÊNCIA ---")
    print(f"Estado: {confluencia['status']}")
    print(f"Direção curta: {confluencia['direcao']}")

    print("\n" + colorir(
        "ANÁLISE INFORMATIVA — NÃO GARANTE RESULTADOS.",
        AMARELO
    ))
    print(colorir(
        "Sem ordens automáticas. Sem Martingale.",
        CINZA
    ))


def registrar_historico(df, curto, longo, horas, confluencia):
    atual = df.iloc[-1]

    registro = {
        "horario": agora_texto(),
        "ativo": ATIVO,
        "preco": atual["close"],
        "atr": atual["atr"],
        "rsi": atual["rsi"],
        "adx": atual["adx"],
        "plus_di": atual["plus_di"],
        "minus_di": atual["minus_di"],
        "momentum": atual["momentum"],
        "momentum_pct": atual["momentum_pct"],
        "momentum_atr": atual["momentum_atr"],
        "curto_status": curto["status"],
        "curto_direcao": curto["direcao"],
        "curto_score_compra": curto["score_compra"],
        "curto_score_venda": curto["score_venda"],
        "curto_alvo": curto["alvo"],
        "longo_status": longo["status"],
        "longo_direcao": longo["direcao"],
        "alvo_1": longo["alvo_1"],
        "alvo_2": longo["alvo_2"],
        "alvo_3": longo["alvo_3"],
        "horas_status": horas["status"],
        "horas_direcao": horas["direcao"],
        "confluencia": confluencia["status"]
    }

    salvar_csv(ARQUIVO_HISTORICO, registro)

    if longo["status"] == "PROJEÇÃO TÉCNICA - NÃO GARANTIDA":
        salvar_csv(ARQUIVO_ALVOS, {
            "horario": agora_texto(),
            "ativo": ATIVO,
            "preco_referencia": atual["close"],
            "direcao": longo["direcao"],
            "alvo_1": longo["alvo_1"],
            "alvo_2": longo["alvo_2"],
            "alvo_3": longo["alvo_3"],
            "status": longo["status"]
        })


def sinal_novo(direcao):
    agora = time.time()
    anterior = ULTIMO_SINAL.get(direcao, 0)

    if agora - anterior < COOLDOWN_SINAL_SEGUNDOS:
        return False

    ULTIMO_SINAL[direcao] = agora
    return True

# ============================================================
# PARTE 6/6 — EXECUÇÃO PRINCIPAL
# ============================================================

def processar_analise(api):
    # Coleta independente dos dois timeframes.
    df_curto = obter_candles(
        api, ATIVO, INTERVALO, QUANTIDADE_CANDLES
    )

    df_curto = calcular_indicadores(df_curto)

    estrutura = analisar_microestrutura(df_curto)
    curto = pontuar_alvo_curto(df_curto, estrutura)
    longo = projetar_alvo_longo(df_curto)

    try:
        df_horas = obter_candles_contexto(api, ATIVO)
        df_horas = calcular_indicadores(df_horas)
        horas = analisar_contexto_horas(df_horas)
    except Exception as erro:
        horas = {
            "status": "CONTEXTO INDISPONÍVEL",
            "direcao": "NEUTRO",
            "score_compra": 0,
            "score_venda": 0,
            "erro": str(erro)
        }

    confluencia = avaliar_confluencia(
        curto, longo, horas
    )

    return df_curto, curto, longo, horas, confluencia


def emitir_novo_sinal(curto, confluencia):
    direcao = curto.get("direcao", "NEUTRO")

    if curto.get("status") != "CANDIDATO":
        return

    if not direcao_permitida(direcao):
        return

    if not sinal_novo(direcao):
        return

    print("\n" + colorir("*" * 58, AMARELO))
    print(colorir("NOVO CANDIDATO TÉCNICO", NEGRITO))
    print(f"Ativo: {ATIVO}")
    print(f"Direção: {direcao}")
    print(f"Confluência: {confluencia['status']}")
    print(
        "Atenção: candidato baseado em indicadores; "
        "não é garantia de resultado."
    )
    print(colorir("*" * 58, AMARELO))


def executar():
    global ATIVO, MODO_ANALISE, FALHAS_CONSECUTIVAS

    ATIVO = selecionar_ativo()
    MODO_ANALISE = selecionar_modo()

    print(f"\nVersão: {VERSAO}")
    print(f"Ativo selecionado: {ATIVO}")
    print(f"Modo selecionado: {MODO_ANALISE}")

    api = conectar_iq()

    ultimo_candle_processado = None

    print("\nIniciando análise. Pressione CTRL+C para encerrar.")

    while True:
        try:
            # Consulta candles reais e fechados.
            # A função de processamento valida os dados recebidos.
            df, curto, longo, horas, confluencia = (
                processar_analise(api)
            )

            FALHAS_CONSECUTIVAS = 0

            timestamp_candle = int(df.iloc[-1]["from"])

            # Recalcula em cada consulta, mas só emite o painel,
            # registra histórico e anuncia candidato em candle novo.
            if timestamp_candle != ultimo_candle_processado:
                ultimo_candle_processado = timestamp_candle

                emitir_painel(
                    df, curto, longo, horas, confluencia
                )

                registrar_historico(
                    df, curto, longo, horas, confluencia
                )

                emitir_novo_sinal(curto, confluencia)

            time.sleep(INTERVALO_LOOP)

        except KeyboardInterrupt:
            print("\nAnálise encerrada pelo usuário.")
            break

        except Exception as erro:
            FALHAS_CONSECUTIVAS += 1

            print(
                colorir(
                    f"\nFalha {FALHAS_CONSECUTIVAS}/"
                    f"{MAX_FALHAS_CONSECUTIVAS}: {erro}",
                    VERMELHO
                )
            )

            # Não cria candles artificiais nem sinaliza com
            # dados incompletos. Interrompe após falhas repetidas.
            if FALHAS_CONSECUTIVAS >= MAX_FALHAS_CONSECUTIVAS:
                print(colorir(
                    "Execução interrompida por falhas consecutivas. "
                    "Verifique conexão, ativo e timeframe.",
                    VERMELHO
                ))
                break

            time.sleep(max(2, INTERVALO_LOOP * 2))

    try:
        if hasattr(api, "close"):
            api.close()
    except Exception:
        pass

    print("QMS encerrado.")


# ============================================================
# INÍCIO DO PROGRAMA
# ============================================================

if __name__ == "__main__":
    try:
        executar()
    except KeyboardInterrupt:
        print("\nPrograma interrompido.")
    except Exception as erro:
        print(f"Erro fatal: {erro}")
        traceback.print_exc()
