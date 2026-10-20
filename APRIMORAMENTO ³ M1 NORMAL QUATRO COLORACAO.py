
# ============================================================
# QMS QUANTUM ANALYST V5.8 M1 — REGRA DE COLORACAO REVISADA
# IQ OPTION / PYDROID 3
# SOMENTE LEITURA | SEM ORDENS | SEM MARTINGALE
# ============================================================

import os
import time
import getpass
from datetime import datetime

import numpy as np
import pandas as pd

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None

VERSAO = "QMS QUANTUM ANALYST V5.8 M1"
ATIVO = "EURUSD-OTC"
CONTA = "PRACTICE"

# M1 = 60 segundos; H1 = 3600 segundos
INTERVALO = 60
INTERVALO_CONTEXTO = 3600
QUANTIDADE_CANDLES = 400
MINIMO_CANDLES = 220
INTERVALO_LOOP = 2
MAX_FALHAS = 12

EMA_RAPIDA = 3
EMA_MEDIA = 30
EMA_TENDENCIA = 60
EMA_LONGA = 200

PERIODO_RSI = 14
PERIODO_ATR = 14
PERIODO_ADX = 14
PERIODO_MOMENTUM = 10

ADX_MINIMO = 16.0
ADX_TENDENCIA_FORTE = 25.0
ATR_MINIMO = 0.0
MAX_ESTICAMENTO_ATR = 1.50

JANELA_MICRO = 5
JANELA_ESTRUTURA_LONGA = 180
ALVO_CURTO_ATR_MIN = 0.8
ALVO_CURTO_ATR_MAX = 2.0
ALVO_LONGO_MIN_ATR = 3.0
FIBONACCI_NIVEIS = (1.272, 1.618, 2.000)

SCORE_MINIMO = 6
MARGEM_DOMINANCIA = 2
COOLDOWN_SINAL = 60

ARQUIVO_HISTORICO = "qms_v58_m1_historico.csv"
ARQUIVO_ALVOS = "qms_v58_m1_alvos.csv"

API = None
ULTIMO_CANDLE = None
ULTIMO_SINAL = {}
ULTIMO_CANDIDATO = None
FALHAS_CONSECUTIVAS = 0

# Cores ANSI para o terminal do Pydroid
RESET = "\033[0m"
VERDE = "\033[1;37;42m"
VERMELHO = "\033[1;37;41m"
AMARELO = "\033[1;30;43m"
CINZA = "\033[1;37;100m"
AZUL = "\033[1;37;44m"


def cor(texto, codigo):
    return f"{codigo}{texto}{RESET}"


def limpar_tela():
    os.system("clear")


def escolher_ativo():
    global ATIVO
    print("\nATIVOS DISPONIVEIS")
    print("1 - EURUSD")
    print("2 - EURUSD-OTC")
    escolha = input("Escolha [2]: ").strip()
    ATIVO = "EURUSD" if escolha == "1" else "EURUSD-OTC"
    print(f"Ativo selecionado: {ATIVO}")


def conectar():
    global API

    if IQ_Option is None:
        raise RuntimeError(
            "Biblioteca ausente. Instale uma versao compativel "
            "de iqoptionapi."
        )

    email = input("E-mail da conta IQ Option: ").strip()
    senha = getpass.getpass("Senha: ")

    API = IQ_Option(email, senha)
    resultado = API.connect()

    # Algumas versoes retornam bool; outras retornam (bool, motivo).
    conectado = (
        resultado[0] if isinstance(resultado, tuple)
        else bool(resultado)
    )

    if not conectado:
        raise RuntimeError(f"Falha na conexao: {resultado}")

    try:
        API.change_balance(CONTA)
    except Exception:
        pass

    print(f"Conectado. Conta solicitada: {CONTA}")
    print("Modo de analise: SOMENTE LEITURA.")


def validar_candles(df, minimo=MINIMO_CANDLES):
    obrigatorias = {"open", "close", "min", "max", "from", "to"}

    if df is None or not isinstance(df, pd.DataFrame):
        raise ValueError("Resposta de candles invalida.")

    if not obrigatorias.issubset(df.columns):
        raise ValueError("Campos OHLC ou timestamps ausentes.")

    df = df.copy()

    for campo in ("open", "close", "min", "max", "from", "to"):
        df[campo] = pd.to_numeric(df[campo], errors="coerce")

    df = df.dropna(subset=list(obrigatorias))
    df = df.sort_values("from").drop_duplicates("from")

    if len(df) < minimo:
        raise ValueError(
            f"Dados insuficientes: {len(df)} candles; "
            f"minimo exigido: {minimo}."
        )

    if (df[["open", "close", "min", "max"]] <= 0).any().any():
        raise ValueError("Precos invalidos ou nao positivos.")

    invalido = (
        (df["max"] < df["min"]) |
        (df["max"] < df["open"]) |
        (df["max"] < df["close"]) |
        (df["min"] > df["open"]) |
        (df["min"] > df["close"])
    )

    if invalido.any():
        raise ValueError("Candles OHLC inconsistentes.")

    if df["from"].duplicated().any():
        raise ValueError("Timestamps duplicados.")

    return df.reset_index(drop=True)


def obter_candles(api, ativo, intervalo, quantidade):
    agora = time.time()
    dados = api.get_candles(ativo, intervalo, quantidade, agora)

    if not dados:
        raise ValueError("API nao retornou candles.")

    df = pd.DataFrame(dados)
    df = validar_candles(df, minimo=quantidade // 2)

    # Considera fechado quando o fim informado do candle ja passou.
    # A semantica dos timestamps deve ser confirmada na API instalada.
    df = df[df["to"] < agora].copy()

    if len(df) < MINIMO_CANDLES:
        raise ValueError(
            "Candles fechados insuficientes apos validacao."
        )

    df = df.tail(quantidade).reset_index(drop=True)

    diferencas = np.diff(df["from"].tail(31).to_numpy())
    if len(diferencas) and not np.all(
        np.abs(diferencas - intervalo) <= 2
    ):
        raise ValueError(
            f"Intervalo inconsistente: esperado {intervalo}s."
        )

    return df


def calcular_rsi(close, periodo=14):
    delta = close.diff()
    ganhos = delta.clip(lower=0)
    perdas = -delta.clip(upper=0)

    media_g = ganhos.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    media_p = perdas.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()

    rs = media_g / media_p.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((media_p == 0) & (media_g > 0), 100)
    rsi = rsi.mask((media_p == 0) & (media_g == 0), 50)
    return rsi


def calcular_atr(df, periodo=14):
    anterior = df["close"].shift(1)
    tr = pd.concat([
        df["max"] - df["min"],
        (df["max"] - anterior).abs(),
        (df["min"] - anterior).abs()
    ], axis=1).max(axis=1)

    return tr.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()


def calcular_adx(df, periodo=14):
    alta = df["max"].diff()
    baixa = -df["min"].diff()

    dm_positivo = alta.where(
        (alta > baixa) & (alta > 0), 0.0
    )
    dm_negativo = baixa.where(
        (baixa > alta) & (baixa > 0), 0.0
    )

    atr = calcular_atr(df, periodo).replace(0, np.nan)

    sm_positivo = dm_positivo.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    sm_negativo = dm_negativo.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()

    di_positivo = 100 * sm_positivo / atr
    di_negativo = 100 * sm_negativo / atr

    soma = (di_positivo + di_negativo).replace(0, np.nan)
    dx = 100 * (di_positivo - di_negativo).abs() / soma

    adx = dx.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()

    return adx, di_positivo, di_negativo


def calcular_indicadores(df):
    df = df.copy()

    for periodo in (3, 30, 60, 200):
        df[f"ema{periodo}"] = df["close"].ewm(
            span=periodo, adjust=False
        ).mean()

    df["rsi"] = calcular_rsi(df["close"], PERIODO_RSI)
    df["atr"] = calcular_atr(df, PERIODO_ATR)

    adx, dip, dim = calcular_adx(df, PERIODO_ADX)
    df["adx"] = adx
    df["di_positivo"] = dip
    df["di_negativo"] = dim

    macd = (
        df["close"].ewm(span=12, adjust=False).mean()
        - df["close"].ewm(span=26, adjust=False).mean()
    )
    df["macd_hist"] = macd - macd.ewm(
        span=9, adjust=False
    ).mean()

    df["momentum"] = (
        df["close"] - df["close"].shift(PERIODO_MOMENTUM)
    ) / df["atr"].replace(0, np.nan)

    df["aceleracao"] = df["momentum"].diff()

    criticos = [
        "ema3", "ema30", "ema60", "ema200",
        "rsi", "atr", "adx", "di_positivo",
        "di_negativo", "macd_hist", "momentum"
    ]

    if df.iloc[-1][criticos].isna().any():
        raise ValueError("Indicadores ainda sem dados validos.")

    return df

def detectar_candle(df):
    atual = df.iloc[-1]
    anterior = df.iloc[-2]

    corpo = abs(atual["close"] - atual["open"])
    amplitude = atual["max"] - atual["min"]

    if amplitude <= 0:
        return "NEUTRO"

    pavio_sup = atual["max"] - max(
        atual["open"], atual["close"]
    )
    pavio_inf = min(
        atual["open"], atual["close"]
    ) - atual["min"]

    engolfo_alta = (
        anterior["close"] < anterior["open"]
        and atual["close"] > atual["open"]
        and atual["open"] <= anterior["close"]
        and atual["close"] >= anterior["open"]
    )

    engolfo_baixa = (
        anterior["close"] > anterior["open"]
        and atual["close"] < atual["open"]
        and atual["open"] >= anterior["close"]
        and atual["close"] <= anterior["open"]
    )

    if engolfo_alta:
        return "ENGOLFO_ALTA"
    if engolfo_baixa:
        return "ENGOLFO_BAIXA"
    if corpo / amplitude <= 0.10:
        return "DOJI"
    if pavio_inf >= corpo * 2 and pavio_sup <= corpo:
        return "REJEICAO_ALTA"
    if pavio_sup >= corpo * 2 and pavio_inf <= corpo:
        return "REJEICAO_BAIXA"
    if atual["close"] > atual["open"] and corpo / amplitude >= 0.70:
        return "CANDLE_FORTE_ALTA"
    if atual["close"] < atual["open"] and corpo / amplitude >= 0.70:
        return "CANDLE_FORTE_BAIXA"

    return "NEUTRO"


def analisar_microestrutura(df):
    atual = df.iloc[-1]
    anteriores = df.iloc[-JANELA_MICRO - 1:-1]

    topo = float(anteriores["max"].max())
    fundo = float(anteriores["min"].min())

    rompimento_alta = atual["close"] > topo
    rompimento_baixa = atual["close"] < fundo

    if atual["ema3"] > atual["ema30"] and atual["close"] > atual["ema3"]:
        micro = "ALTA"
    elif atual["ema3"] < atual["ema30"] and atual["close"] < atual["ema3"]:
        micro = "BAIXA"
    else:
        micro = "MISTA"

    return {
        "micro": micro,
        "topo": topo,
        "fundo": fundo,
        "rompimento_alta": bool(rompimento_alta),
        "rompimento_baixa": bool(rompimento_baixa),
        "padrao": detectar_candle(df)
    }


def avaliar_mercado(df):
    a = df.iloc[-1]
    anterior = df.iloc[-2]
    micro = analisar_microestrutura(df)

    compra = 0
    venda = 0
    motivos_compra = []
    motivos_venda = []

    # 1. Alinhamento das medias
    if a["ema3"] > a["ema30"] > a["ema60"] > a["ema200"]:
        compra += 2
        motivos_compra.append("EMAs alinhadas para alta")
    elif a["ema3"] < a["ema30"] < a["ema60"] < a["ema200"]:
        venda += 2
        motivos_venda.append("EMAs alinhadas para baixa")

    # 2. Posicao e inclinacao da EMA30
    inclinacao30 = a["ema30"] - anterior["ema30"]
    if a["close"] > a["ema30"] and inclinacao30 > 0:
        compra += 1
        motivos_compra.append("Preco acima da EMA30")
    elif a["close"] < a["ema30"] and inclinacao30 < 0:
        venda += 1
        motivos_venda.append("Preco abaixo da EMA30")

    # 3. Direcao DMI
    if a["di_positivo"] > a["di_negativo"]:
        compra += 1
        motivos_compra.append("DI+ dominante")
    elif a["di_negativo"] > a["di_positivo"]:
        venda += 1
        motivos_venda.append("DI- dominante")

    # 4. RSI sem exigir sobrecompra/sobrevenda extrema
    if 52 <= a["rsi"] < 70:
        compra += 1
        motivos_compra.append("RSI favorece alta")
    elif 30 < a["rsi"] <= 48:
        venda += 1
        motivos_venda.append("RSI favorece baixa")

    # 5. MACD
    if a["macd_hist"] > 0:
        compra += 1
        motivos_compra.append("MACD positivo")
    elif a["macd_hist"] < 0:
        venda += 1
        motivos_venda.append("MACD negativo")

    # 6. Microestrutura / rompimento
    if micro["micro"] == "ALTA":
        compra += 1
        motivos_compra.append("Microtendencia de alta")
    elif micro["micro"] == "BAIXA":
        venda += 1
        motivos_venda.append("Microtendencia de baixa")

    if micro["rompimento_alta"]:
        compra += 1
        motivos_compra.append("Rompimento do topo recente")
    if micro["rompimento_baixa"]:
        venda += 1
        motivos_venda.append("Rompimento do fundo recente")

    if micro["padrao"] in ("ENGOLFO_ALTA", "REJEICAO_ALTA", "CANDLE_FORTE_ALTA"):
        compra += 1
        motivos_compra.append(micro["padrao"])
    elif micro["padrao"] in ("ENGOLFO_BAIXA", "REJEICAO_BAIXA", "CANDLE_FORTE_BAIXA"):
        venda += 1
        motivos_venda.append(micro["padrao"])

    atr = float(a["atr"])
    preco = float(a["close"])
    esticamento = abs(preco - a["ema30"]) / atr if atr > 0 else np.inf

    momentum_compra = (
        a["momentum"] > 0 and a["aceleracao"] >= 0
    )
    momentum_venda = (
        a["momentum"] < 0 and a["aceleracao"] <= 0
    )

    filtros = {
        "ADX": bool(a["adx"] >= ADX_MINIMO),
        "ATR": bool(atr > ATR_MINIMO),
        "Momentum": bool(momentum_compra or momentum_venda),
        "Sem esticamento": bool(esticamento <= MAX_ESTICAMENTO_ATR),
    }

    tendencia_alta = (
        a["ema3"] > a["ema30"] > a["ema60"] > a["ema200"]
        and preco > a["ema30"]
    )
    tendencia_baixa = (
        a["ema3"] < a["ema30"] < a["ema60"] < a["ema200"]
        and preco < a["ema30"]
    )

    # Direcao precisa ter vantagem sobre o lado contrario.
    direcao = "MISTA"
    if compra >= SCORE_MINIMO and compra - venda >= MARGEM_DOMINANCIA:
        direcao = "COMPRA"
    elif venda >= SCORE_MINIMO and venda - compra >= MARGEM_DOMINANCIA:
        direcao = "VENDA"

    # Coloracao: tendencia + forca + filtros.
    # Amarelo indica transicao/conflito; cinza, lateral ou dados fracos.
    filtros_ok = all(filtros.values())

    if direcao == "COMPRA" and tendencia_alta and filtros_ok and momentum_compra:
        cor_status = "ALTA_CONFIRMADA"
        cor_terminal = VERDE
    elif direcao == "VENDA" and tendencia_baixa and filtros_ok and momentum_venda:
        cor_status = "BAIXA_CONFIRMADA"
        cor_terminal = VERMELHO
    elif direcao in ("COMPRA", "VENDA"):
        cor_status = "TRANSICAO_OU_FILTROS_PENDENTES"
        cor_terminal = AMARELO
    elif a["adx"] < ADX_MINIMO or abs(compra - venda) < MARGEM_DOMINANCIA:
        cor_status = "LATERAL_OU_SEM_DOMINANCIA"
        cor_terminal = CINZA
    else:
        cor_status = "CONFLITO"
        cor_terminal = AMARELO

    # Aprovar sinal exige concordancia de direcao, tendencia e filtros.
    aprovado = (
        cor_status in ("ALTA_CONFIRMADA", "BAIXA_CONFIRMADA")
        and direcao in ("COMPRA", "VENDA")
    )

    return {
        "direcao": direcao,
        "cor_status": cor_status,
        "cor_terminal": cor_terminal,
        "aprovado": bool(aprovado),
        "compra": int(compra),
        "venda": int(venda),
        "motivos_compra": motivos_compra,
        "motivos_venda": motivos_venda,
        "filtros": filtros,
        "micro": micro,
        "esticamento_atr": float(esticamento),
        "tendencia_alta": bool(tendencia_alta),
        "tendencia_baixa": bool(tendencia_baixa)
    }

def analisar_contexto_h1(api, ativo):
    try:
        df = obter_candles(
            api, ativo, INTERVALO_CONTEXTO, 240
        )
        df = calcular_indicadores(df)
        a = df.iloc[-1]

        if (
            a["ema3"] > a["ema30"] > a["ema60"] > a["ema200"]
            and a["di_positivo"] > a["di_negativo"]
            and a["macd_hist"] > 0
            and a["adx"] >= ADX_MINIMO
        ):
            return "ALTA"

        if (
            a["ema3"] < a["ema30"] < a["ema60"] < a["ema200"]
            and a["di_negativo"] > a["di_positivo"]
            and a["macd_hist"] < 0
            and a["adx"] >= ADX_MINIMO
        ):
            return "BAIXA"

        return "MISTA"
    except Exception:
        return "INDISPONIVEL"


def calcular_alvos(df, direcao):
    a = df.iloc[-1]
    preco = float(a["close"])
    atr = float(a["atr"])

    if atr <= 0 or not np.isfinite(atr):
        return {}

    sinal = 1 if direcao == "COMPRA" else -1

    alvo_curto = preco + sinal * atr * ALVO_CURTO_ATR_MIN
    alvo_curto_max = preco + sinal * atr * ALVO_CURTO_ATR_MAX

    janela = df.tail(JANELA_ESTRUTURA_LONGA)
    topo = float(janela["max"].max())
    fundo = float(janela["min"].min())
    amplitude = max(topo - fundo, atr * ALVO_LONGO_MIN_ATR)

    # Projecoes tecnicas heuristicas, nao previsoes garantidas.
    base = preco
    alvos_longos = [
        base + sinal * max(amplitude * nivel, atr * ALVO_LONGO_MIN_ATR)
        for nivel in FIBONACCI_NIVEIS
    ]

    return {
        "curto": alvo_curto,
        "curto_max": alvo_curto_max,
        "topo_estrutura": topo,
        "fundo_estrutura": fundo,
        "longos": alvos_longos
    }


def fmt_preco(valor):
    try:
        return f"{float(valor):.6f}"
    except (TypeError, ValueError):
        return "N/D"


def fmt_num(valor, casas=2):
    try:
        return f"{float(valor):.{casas}f}"
    except (TypeError, ValueError):
        return "N/D"


def emitir_painel(df, analise, contexto, alvos):
    a = df.iloc[-1]
    status = analise["cor_status"]
    c = analise["cor_terminal"]

    limpar_tela()
    print(cor("=" * 58, AZUL))
    print(cor(VERSAO.center(58), AZUL))
    print(cor("=" * 58, AZUL))
    print(f"Ativo: {ATIVO} | Grafico: M1 | Contexto: H1")
    print("Modo: SOMENTE LEITURA | Ordens automaticas: DESATIVADAS")
    print("-" * 58)
    print(cor(f"COLORACAO: {status}", c))
    print(f"Direcao predominante: {analise['direcao']}")
    print(
        f"Pontuacao: COMPRA {analise['compra']} | "
        f"VENDA {analise['venda']}"
    )
    print(
        "Liberacao tecnica: "
        + ("APROVADA" if analise["aprovado"] else "NAO APROVADA")
    )
    print(f"Contexto H1: {contexto}")
    print("-" * 58)

    print(f"Preco fechado: {fmt_preco(a['close'])}")
    print(
        f"EMA 3: {fmt_preco(a['ema3'])} | "
        f"EMA 30: {fmt_preco(a['ema30'])}"
    )
    print(
        f"EMA 60: {fmt_preco(a['ema60'])} | "
        f"EMA 200: {fmt_preco(a['ema200'])}"
    )
    print(
        f"RSI: {fmt_num(a['rsi'])} | ATR: {fmt_num(a['atr'], 6)}"
    )
    print(
        f"ADX: {fmt_num(a['adx'])} | "
        f"DI+: {fmt_num(a['di_positivo'])} | "
        f"DI-: {fmt_num(a['di_negativo'])}"
    )
    print(
        f"MACD hist.: {fmt_num(a['macd_hist'], 6)} | "
        f"Momentum/ATR: {fmt_num(a['momentum'])} | "
        f"Aceleracao: {fmt_num(a['aceleracao'])}"
    )

    micro = analise["micro"]
    print(
        f"Microtendencia: {micro['micro']} | "
        f"Padrao: {micro['padrao']}"
    )
    print(
        f"Rompimento alta: {micro['rompimento_alta']} | "
        f"Rompimento baixa: {micro['rompimento_baixa']}"
    )
    print(f"Esticamento EMA30: {fmt_num(analise['esticamento_atr'])} ATR")

    print("\nFILTROS:")
    for nome, ok in analise["filtros"].items():
        print(f"  {nome}: {'OK' if ok else 'PENDENTE'}")

    if analise["direcao"] == "COMPRA":
        print("Motivos: " + ", ".join(analise["motivos_compra"]))
    elif analise["direcao"] == "VENDA":
        print("Motivos: " + ", ".join(analise["motivos_venda"]))

    if alvos:
        print("\nALVOS TECNICOS ESTIMADOS:")
        print(f"Curto: {fmt_preco(alvos['curto'])}")
        print(f"Curto estendido: {fmt_preco(alvos['curto_max'])}")
        print(
            f"Estrutura: topo {fmt_preco(alvos['topo_estrutura'])} | "
            f"fundo {fmt_preco(alvos['fundo_estrutura'])}"
        )
        for i, alvo in enumerate(alvos["longos"], 1):
            print(f"Alvo longo {i}: {fmt_preco(alvo)}")

    horario = datetime.fromtimestamp(int(a["to"])).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    print(f"\nUltimo candle fechado: {horario}")
    print("Alvos sao estimativas tecnicas, nao garantias.")
    print("=" * 58)


def salvar_registro(df, analise, contexto, alvos):
    a = df.iloc[-1]
    registro = {
        "ativo": ATIVO,
        "timestamp": int(a["to"]),
        "close": float(a["close"]),
        "ema3": float(a["ema3"]),
        "ema30": float(a["ema30"]),
        "ema60": float(a["ema60"]),
        "ema200": float(a["ema200"]),
        "rsi": float(a["rsi"]),
        "atr": float(a["atr"]),
        "adx": float(a["adx"]),
        "di_positivo": float(a["di_positivo"]),
        "di_negativo": float(a["di_negativo"]),
        "macd_hist": float(a["macd_hist"]),
        "momentum": float(a["momentum"]),
        "score_compra": analise["compra"],
        "score_venda": analise["venda"],
        "direcao": analise["direcao"],
        "coloracao": analise["cor_status"],
        "aprovado": analise["aprovado"],
        "contexto_h1": contexto,
        "alvo_curto": alvos.get("curto"),
        "alvo_curto_max": alvos.get("curto_max"),
        "alvos_longos": str(alvos.get("longos", []))
    }

    arquivo = ARQUIVO_HISTORICO
    pd.DataFrame([registro]).to_csv(
        arquivo,
        mode="a",
        header=not os.path.exists(arquivo),
        index=False
    )

    if alvos:
        pd.DataFrame([{
            "ativo": ATIVO,
            "timestamp": int(a["to"]),
            "preco": float(a["close"]),
            "direcao": analise["direcao"],
            "alvo_curto": alvos["curto"],
            "alvo_curto_max": alvos["curto_max"],
            "alvos_longos": str(alvos["longos"]),
            "aviso": "PROJECAO TECNICA NAO GARANTIDA"
        }]).to_csv(
            ARQUIVO_ALVOS,
            mode="a",
            header=not os.path.exists(ARQUIVO_ALVOS),
            index=False
        )


def emitir_sinal_novo(analise, timestamp):
    global ULTIMO_SINAL

    if not analise["aprovado"]:
        return

    direcao = analise["direcao"]
    chave = (ATIVO, direcao)
    agora = time.time()

    ultimo = ULTIMO_SINAL.get(chave, {})
    if (
        ultimo.get("timestamp") == timestamp
        or agora - ultimo.get("horario", 0) < COOLDOWN_SINAL
    ):
        return

    ULTIMO_SINAL[chave] = {
        "timestamp": timestamp,
        "horario": agora
    }

    cor_sinal = VERDE if direcao == "COMPRA" else VERMELHO
    print("\n" + cor(
        f"NOVO SINAL TECNICO M1: {direcao}", cor_sinal
    ))
    print("Este sinal e informativo; nenhuma ordem foi enviada.")


def emitir_candidato_novo(analise, timestamp):
    global ULTIMO_CANDIDATO

    if analise["direcao"] not in ("COMPRA", "VENDA"):
        ULTIMO_CANDIDATO = None
        return

    if analise["aprovado"]:
        ULTIMO_CANDIDATO = None
        return

    estado = (
        timestamp,
        analise["direcao"],
        analise["compra"],
        analise["venda"],
        tuple(k for k, v in analise["filtros"].items() if not v)
    )

    if estado == ULTIMO_CANDIDATO:
        return

    ULTIMO_CANDIDATO = estado
    pendentes = [
        nome for nome, ok in analise["filtros"].items() if not ok
    ]

    print(cor(
        f"CANDIDATO {analise['direcao']} - NAO APROVADO",
        AMARELO
    ))
    print("Filtros pendentes: " + (
        ", ".join(pendentes) if pendentes else "confirmacao de tendencia"
    ))


def processar(api):
    global ULTIMO_CANDLE

    df = obter_candles(api, ATIVO, INTERVALO, QUANTIDADE_CANDLES)
    timestamp = int(df.iloc[-1]["to"])

    if timestamp == ULTIMO_CANDLE:
        return

    df = calcular_indicadores(df)
    analise = avaliar_mercado(df)
    contexto = analisar_contexto_h1(api, ATIVO)

    # H1 contrario bloqueia a aprovacao, mas nao altera os dados brutos.
    if analise["direcao"] == "COMPRA" and contexto == "BAIXA":
        analise["aprovado"] = False
        analise["cor_status"] = "CONFLITO_COM_H1"
        analise["cor_terminal"] = AMARELO
    elif analise["direcao"] == "VENDA" and contexto == "ALTA":
        analise["aprovado"] = False
        analise["cor_status"] = "CONFLITO_COM_H1"
        analise["cor_terminal"] = AMARELO

    alvos = {}
    if analise["direcao"] in ("COMPRA", "VENDA"):
        alvos = calcular_alvos(df, analise["direcao"])

    emitir_painel(df, analise, contexto, alvos)
    salvar_registro(df, analise, contexto, alvos)
    emitir_candidato_novo(analise, timestamp)
    emitir_sinal_novo(analise, timestamp)

    ULTIMO_CANDLE = timestamp


def executar():
    global FALHAS_CONSECUTIVAS

    escolher_ativo()
    conectar()

    try:
        while True:
            try:
                if hasattr(API, "check_connect") and not API.check_connect():
                    resultado = API.connect()
                    conectado = (
                        resultado[0] if isinstance(resultado, tuple)
                        else bool(resultado)
                    )
                    if not conectado:
                        raise RuntimeError("Reconexao falhou.")

                processar(API)
                FALHAS_CONSECUTIVAS = 0

            except KeyboardInterrupt:
                print("\nExecucao encerrada pelo usuario.")
                break

            except Exception as erro:
                FALHAS_CONSECUTIVAS += 1
                print(
                    f"\nFalha {FALHAS_CONSECUTIVAS}/{MAX_FALHAS}: "
                    f"{erro}"
                )

                if FALHAS_CONSECUTIVAS >= MAX_FALHAS:
                    print("Parada segura por falhas consecutivas.")
                    break

            time.sleep(INTERVALO_LOOP)

    finally:
        if API is not None and hasattr(API, "close"):
            try:
                API.close()
            except Exception:
                pass


if __name__ == "__main__":
    executar()
