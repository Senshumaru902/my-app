# ============================================================
# QMS MULTITEMPORAL M1 - PADROES + PERNADAS
# IQ OPTION | PYDROID 3 | SOMENTE LEITURA
#
# PERIODOS MONITORADOS: 5s, 15s e 30s
#
# MODULOS:
# 1. CRUZ: EMA 3/9
# 2. FORCA: corpo >= 65% e sombra contraria <= 20%
# 3. FORMACAO: tres soldados / tres corvos
# 4. PERNADA: movimento direcional dinamico, usando:
#       - ATR medio
#       - deslocamento liquido
#       - eficiencia do movimento
#       - predominancia de candles na direcao
#
# QUALQUER MODULO, EM QUALQUER PERIODO, PODE INICIAR.
# Os quatro modulos precisam estar alinhados para o sinal final.
# A ordem de chegada nao importa.
#
# COMPRA: cruz alta + forca alta + soldados + pernada alta.
# VENDA : cruz baixa + forca baixa + corvos + pernada baixa.
#
# Nao envia ordens. Nao executa compra ou venda.
# ============================================================

import os
import time
import getpass
import traceback

from iqoptionapi.stable_api import IQ_Option


# ============================================================
# CONFIGURACOES
# ============================================================

ATIVO = "EURUSD-OTC"
CONTA = "PRACTICE"

TIMEFRAMES = [5, 15, 30]

EMA_RAPIDA = 3
EMA_LENTA = 9

CORPO_FORCA = 0.65
SOMBRA_CONTRARIA_MAX = 0.20

# Parametros da pernada
PERIODO_PERNADA = 8
PERIODO_ATR = 14
MIN_CANDLES_DIRECAO = 5
EFICIENCIA_MINIMA = 0.55
DESLOCAMENTO_ATR_MINIMO = 1.20

VALIDADE_SEQUENCIA = 60
INTERVALO_ATUALIZACAO = 1.0
QUANTIDADE_HISTORICO = 150
MARGEM_FECHAMENTO = 0.25

UM_SINAL_POR_MINUTO = True


# ============================================================
# LOGIN
# ============================================================

print("=" * 60)
print("QMS MULTITEMPORAL M1 - PADROES + PERNADAS")
print("=" * 60)

EMAIL = input("Email IQ Option: ").strip()
SENHA = getpass.getpass("Senha IQ Option: ")

api = IQ_Option(EMAIL, SENHA)


# ============================================================
# ESTADO GLOBAL
# ============================================================

dados_mercado = {p: [] for p in TIMEFRAMES}
ultimo_candle_processado = {p: None for p in TIMEFRAMES}

# Impede que o mesmo evento de candle seja processado duas vezes.
eventos_processados = set()

# Estado da sequencia atual.
sequencia = {
    "direcao": None,
    "eventos": {},
    "inicio": None
}

# Estado da pernada por periodo. A pernada e um estado dinamico,
# nao apenas um pulso de um unico candle.
estado_pernadas = {
    p: {
        "direcao": None,
        "tempo": None,
        "forca": 0.0,
        "eficiencia": 0.0,
        "deslocamento_atr": 0.0
    }
    for p in TIMEFRAMES
}

ultimo_sinal = "NENHUM"
ultimo_sinal_minuto = None


# ============================================================
# FUNCOES AUXILIARES
# ============================================================

def limpar_tela():
    os.system("cls" if os.name == "nt" else "clear")


def obter_fechamento(candle, periodo):
    fechamento = candle.get("to")
    if fechamento is None:
        fechamento = float(candle.get("from", 0)) + periodo
    return float(fechamento)


def normalizar_candles(lista, periodo):
    """Normaliza OHLC e mantem apenas candles fechados."""
    resultado = []

    if isinstance(lista, dict):
        lista = list(lista.values())

    agora = time.time()

    for bruto in lista:
        try:
            inicio = float(bruto.get("from", 0))
            fechamento = obter_fechamento(bruto, periodo)

            if inicio <= 0:
                continue

            if fechamento > agora - MARGEM_FECHAMENTO:
                continue

            maxima = bruto.get("max", bruto.get("high"))
            minima = bruto.get("min", bruto.get("low"))

            if maxima is None or minima is None:
                continue

            candle = {
                "from": inicio,
                "to": fechamento,
                "open": float(bruto["open"]),
                "close": float(bruto["close"]),
                "max": float(maxima),
                "min": float(minima)
            }

            if candle["max"] < candle["min"]:
                continue
            if candle["max"] < max(candle["open"], candle["close"]):
                continue
            if candle["min"] > min(candle["open"], candle["close"]):
                continue

            resultado.append(candle)

        except (TypeError, ValueError, KeyError):
            continue

    resultado.sort(key=lambda item: item["from"])

    unicos = {}
    for candle in resultado:
        unicos[candle["from"]] = candle

    return list(unicos.values())


def ema(valores, periodo):
    if len(valores) < periodo:
        return None

    fator = 2.0 / (periodo + 1.0)
    resultado = float(valores[0])

    for valor in valores[1:]:
        resultado = float(valor) * fator + resultado * (1.0 - fator)

    return resultado


def calcular_atr(candles, periodo=14):
    if len(candles) < periodo + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        atual = candles[i]
        anterior = candles[i - 1]

        tr = max(
            atual["max"] - atual["min"],
            abs(atual["max"] - anterior["close"]),
            abs(atual["min"] - anterior["close"])
        )
        ranges.append(tr)

    if len(ranges) < periodo:
        return None

    janela = ranges[-periodo:]
    return sum(janela) / len(janela)


def direcao_texto(direcao):
    return "ALTA / COMPRA" if direcao == "CALL" else "BAIXA / VENDA"


# ============================================================
# HISTORICO E STREAMS
# ============================================================

def carregar_historico():
    for periodo in TIMEFRAMES:
        try:
            bruto = api.get_candles(
                ATIVO,
                periodo,
                QUANTIDADE_HISTORICO,
                time.time()
            )
            dados_mercado[periodo] = normalizar_candles(bruto, periodo)
        except Exception as erro:
            print("Falha no historico", periodo, "s:", erro)


def atualizar_candles(periodo):
    try:
        bruto = api.get_realtime_candles(ATIVO, periodo)
        novos = normalizar_candles(bruto, periodo)

        if not novos:
            return

        combinados = {
            candle["from"]: candle
            for candle in dados_mercado[periodo]
        }

        for candle in novos:
            combinados[candle["from"]] = candle

        ordenados = sorted(
            combinados.values(),
            key=lambda item: item["from"]
        )

        dados_mercado[periodo] = ordenados[-QUANTIDADE_HISTORICO:]

    except Exception:
        pass


# ============================================================
# MODULO 1 - CRUZAMENTO EMA 3 / EMA 9
# ============================================================

def detectar_cruz(periodo):
    candles = dados_mercado[periodo]

    if len(candles) < 12:
        return None

    fechamentos = [c["close"] for c in candles]

    ema3_anterior = ema(fechamentos[:-1], EMA_RAPIDA)
    ema9_anterior = ema(fechamentos[:-1], EMA_LENTA)
    ema3_atual = ema(fechamentos, EMA_RAPIDA)
    ema9_atual = ema(fechamentos, EMA_LENTA)

    if any(v is None for v in (
        ema3_anterior, ema9_anterior, ema3_atual, ema9_atual
    )):
        return None

    if ema3_anterior <= ema9_anterior and ema3_atual > ema9_atual:
        return "CALL"

    if ema3_anterior >= ema9_anterior and ema3_atual < ema9_atual:
        return "PUT"

    return None


# ============================================================
# MODULO 2 - CANDLE DE FORCA
# ============================================================

def detectar_forca(periodo):
    candles = dados_mercado[periodo]

    if len(candles) < 2:
        return None

    c = candles[-1]
    abertura = c["open"]
    fechamento = c["close"]
    maxima = c["max"]
    minima = c["min"]

    amplitude = maxima - minima
    if amplitude <= 0:
        return None

    corpo_pct = abs(fechamento - abertura) / amplitude
    sombra_sup_pct = (
        maxima - max(abertura, fechamento)
    ) / amplitude
    sombra_inf_pct = (
        min(abertura, fechamento) - minima
    ) / amplitude

    if fechamento > abertura:
        if (
            corpo_pct >= CORPO_FORCA
            and sombra_sup_pct <= SOMBRA_CONTRARIA_MAX
        ):
            return "CALL"

    elif fechamento < abertura:
        if (
            corpo_pct >= CORPO_FORCA
            and sombra_inf_pct <= SOMBRA_CONTRARIA_MAX
        ):
            return "PUT"

    return None


# ============================================================
# MODULO 3 - TRES SOLDADOS / TRES CORVOS
# ============================================================

def detectar_formacao(periodo):
    candles = dados_mercado[periodo]

    if len(candles) < 3:
        return None

    c1, c2, c3 = candles[-3:]

    soldados = (
        c1["close"] > c1["open"]
        and c2["close"] > c2["open"]
        and c3["close"] > c3["open"]
        and c2["close"] > c1["close"]
        and c3["close"] > c2["close"]
        and c2["open"] >= c1["open"]
        and c3["open"] >= c2["open"]
    )

    if soldados:
        return "CALL"

    corvos = (
        c1["close"] < c1["open"]
        and c2["close"] < c2["open"]
        and c3["close"] < c3["open"]
        and c2["close"] < c1["close"]
        and c3["close"] < c2["close"]
        and c2["open"] <= c1["open"]
        and c3["open"] <= c2["open"]
    )

    if corvos:
        return "PUT"

    return None


# ============================================================
# MODULO 4 - PERNADA DINAMICA DE ALTA / BAIXA
# ============================================================

def detectar_pernada(periodo):
    """
    Detecta uma pernada em andamento.

    CALL:
      - deslocamento liquido positivo;
      - eficiencia minima;
      - maioria dos candles direcionais de alta;
      - deslocamento minimo em relacao ao ATR.

    PUT: criterios inversos.

    Retorna (direcao, metricas) ou (None, metricas).
    """
    candles = dados_mercado[periodo]

    minimo = max(PERIODO_PERNADA + 1, PERIODO_ATR + 1)
    if len(candles) < minimo:
        return None, None

    janela = candles[-PERIODO_PERNADA:]
    primeiro = janela[0]
    ultimo = janela[-1]

    atr = calcular_atr(candles, PERIODO_ATR)
    if atr is None or atr <= 0:
        return None, None

    deslocamento = ultimo["close"] - primeiro["open"]

    soma_movimentos = 0.0
    altas = 0
    baixas = 0

    for c in janela:
        movimento = c["close"] - c["open"]
        soma_movimentos += abs(movimento)

        if movimento > 0:
            altas += 1
        elif movimento < 0:
            baixas += 1

    if soma_movimentos <= 0:
        return None, None

    eficiencia = abs(deslocamento) / soma_movimentos
    deslocamento_atr = abs(deslocamento) / atr

    predominancia_alta = altas >= MIN_CANDLES_DIRECAO
    predominancia_baixa = baixas >= MIN_CANDLES_DIRECAO

    metricas = {
        "atr": atr,
        "eficiencia": eficiencia,
        "deslocamento_atr": deslocamento_atr,
        "altas": altas,
        "baixas": baixas,
        "inicio": primeiro["from"],
        "fim": ultimo["to"]
    }

    if (
        deslocamento > 0
        and predominancia_alta
        and eficiencia >= EFICIENCIA_MINIMA
        and deslocamento_atr >= DESLOCAMENTO_ATR_MINIMO
    ):
        return "CALL", metricas

    if (
        deslocamento < 0
        and predominancia_baixa
        and eficiencia >= EFICIENCIA_MINIMA
        and deslocamento_atr >= DESLOCAMENTO_ATR_MINIMO
    ):
        return "PUT", metricas

    return None, metricas


def atualizar_estado_pernadas(periodo):
    direcao, metricas = detectar_pernada(periodo)

    if direcao is None:
        estado_pernadas[periodo] = {
            "direcao": None,
            "tempo": None,
            "forca": 0.0,
            "eficiencia": (
                metricas["eficiencia"] if metricas else 0.0
            ),
            "deslocamento_atr": (
                metricas["deslocamento_atr"] if metricas else 0.0
            )
        }
        return

    # A pernada fica ativa enquanto o conjunto de criterios
    # continuar verdadeiro nos candles fechados mais recentes.
    estado_pernadas[periodo] = {
        "direcao": direcao,
        "tempo": metricas["fim"],
        "forca": metricas["deslocamento_atr"],
        "eficiencia": metricas["eficiencia"],
        "deslocamento_atr": metricas["deslocamento_atr"]
    }


def melhor_pernada_ativa():
    """
    Escolhe uma pernada ativa e recente, sem timeframe prioritario.
    Usa o evento mais recente; em empate, maior deslocamento/ATR.
    """
    candidatas = []

    agora = time.time()

    for periodo, estado in estado_pernadas.items():
        if estado["direcao"] is None or estado["tempo"] is None:
            continue

        idade = agora - estado["tempo"]

        if idade < 0 or idade > VALIDADE_SEQUENCIA:
            continue

        candidatas.append((
            estado["tempo"],
            estado["forca"],
            periodo,
            estado["direcao"]
        ))

    if not candidatas:
        return None

    candidatas.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True
    )

    tempo, forca, periodo, direcao = candidatas[0]

    return {
        "direcao": direcao,
        "periodo": periodo,
        "tempo": tempo,
        "forca": forca
    }


# ============================================================
# CONTROLE DA SEQUENCIA
# ============================================================

def cancelar_sequencia(motivo):
    global sequencia

    if sequencia["direcao"] is not None:
        print("\nSEQUENCIA CANCELADA:", motivo)

    sequencia = {
        "direcao": None,
        "eventos": {},
        "inicio": None
    }


def registrar_evento(modulo, direcao, periodo, fechamento, detalhes=None):
    global sequencia

    agora = time.time()

    if agora - fechamento > VALIDADE_SEQUENCIA:
        return

    if sequencia["direcao"] is None:
        sequencia["direcao"] = direcao
        sequencia["inicio"] = fechamento
        sequencia["eventos"][modulo] = {
            "direcao": direcao,
            "periodo": periodo,
            "tempo": fechamento,
            "detalhes": detalhes
        }

        print(
            "\nPRIMEIRO PADRAO:",
            modulo,
            direcao_texto(direcao),
            "|", periodo, "s"
        )

    elif sequencia["direcao"] != direcao:
        cancelar_sequencia("PADRAO CONTRARIO")

        sequencia["direcao"] = direcao
        sequencia["inicio"] = fechamento
        sequencia["eventos"][modulo] = {
            "direcao": direcao,
            "periodo": periodo,
            "tempo": fechamento,
            "detalhes": detalhes
        }

        print(
            "\nNOVA SEQUENCIA:",
            modulo,
            direcao_texto(direcao),
            "|", periodo, "s"
        )

    elif modulo not in sequencia["eventos"]:
        sequencia["eventos"][modulo] = {
            "direcao": direcao,
            "periodo": periodo,
            "tempo": fechamento,
            "detalhes": detalhes
        }

        print(
            "CONFIRMADO:",
            modulo,
            direcao_texto(direcao),
            "|", periodo, "s"
        )

    verificar_sinal_final()


def verificar_sinal_final():
    global ultimo_sinal
    global ultimo_sinal_minuto

    necessarios = {"CRUZ", "FORCA", "FORMACAO", "PERNADA"}

    if set(sequencia["eventos"].keys()) != necessarios:
        return

    direcoes = [
        evento["direcao"]
        for evento in sequencia["eventos"].values()
    ]

    if len(set(direcoes)) != 1:
        cancelar_sequencia("DIRECOES DIFERENTES")
        return

    agora = time.time()

    for evento in sequencia["eventos"].values():
        if agora - evento["tempo"] > VALIDADE_SEQUENCIA:
            cancelar_sequencia("CONFIRMACAO EXPIRADA")
            return

    minuto_atual = int(agora // 60)

    if UM_SINAL_POR_MINUTO and ultimo_sinal_minuto == minuto_atual:
        cancelar_sequencia("LIMITE DE UM SINAL POR MINUTO")
        return

    direcao = direcoes[0]
    ultimo_sinal = direcao
    ultimo_sinal_minuto = minuto_atual

    print("\n" + "=" * 60)
    print("             SINAL FINAL:", "COMPRA" if direcao == "CALL" else "VENDA")
    print("=" * 60)

    for modulo, evento in sequencia["eventos"].items():
        print(
            modulo,
            "| periodo:", evento["periodo"], "s",
            "| horario:", time.strftime(
                "%H:%M:%S",
                time.localtime(evento["tempo"])
            )
        )

        if modulo == "PERNADA" and evento["detalhes"]:
            print(
                "   deslocamento/ATR:",
                round(evento["detalhes"]["deslocamento_atr"], 2),
                "| eficiencia:",
                round(evento["detalhes"]["eficiencia"], 2)
            )

    print("REFERENCIA: GRAFICO M1")
    print("HORARIO DO SINAL:", time.strftime("%H:%M:%S"))
    print("=" * 60)

    cancelar_sequencia("SINAL FINAL EMITIDO")


def verificar_expiracao():
    if sequencia["inicio"] is None:
        return

    if time.time() - sequencia["inicio"] > VALIDADE_SEQUENCIA:
        cancelar_sequencia("JANELA DE 60 SEGUNDOS EXPIRADA")


# ============================================================
# PROCESSAR CANDLE NOVO DE CADA PERIODO
# ============================================================

def processar_periodo(periodo):
    candles = dados_mercado[periodo]

    if len(candles) < max(12, PERIODO_ATR + 1):
        return

    candle = candles[-1]
    fechamento = candle["to"]

    if ultimo_candle_processado[periodo] == fechamento:
        return

    ultimo_candle_processado[periodo] = fechamento

    # Atualiza o estado dinamico da pernada.
    atualizar_estado_pernadas(periodo)

    resultados = (
        ("CRUZ", detectar_cruz(periodo), None),
        ("FORCA", detectar_forca(periodo), None),
        ("FORMACAO", detectar_formacao(periodo), None)
    )

    for modulo, direcao, detalhes in resultados:
        if direcao is None:
            continue

        chave = (modulo, direcao, periodo, fechamento)

        if chave in eventos_processados:
            continue

        eventos_processados.add(chave)

        registrar_evento(
            modulo,
            direcao,
            periodo,
            fechamento,
            detalhes
        )

    # A pernada pode iniciar a sequencia ou confirmar os demais.
    pernada = melhor_pernada_ativa()

    if pernada is not None:
        # Registra uma vez por periodo/candle de fechamento.
        chave_pernada = (
            "PERNADA",
            pernada["direcao"],
            pernada["periodo"],
            pernada["tempo"]
        )

        if chave_pernada not in eventos_processados:
            eventos_processados.add(chave_pernada)

            registrar_evento(
                "PERNADA",
                pernada["direcao"],
                pernada["periodo"],
                pernada["tempo"],
                {
                    "deslocamento_atr": pernada["forca"],
                    "eficiencia": estado_pernadas[
                        pernada["periodo"]
                    ]["eficiencia"]
                }
            )


# ============================================================
# PAINEL
# ============================================================

def mostrar_painel():
    limpar_tela()

    print("=" * 60)
    print("       QMS MULTITEMPORAL M1 - PADROES + PERNADAS")
    print("=" * 60)
    print("ATIVO:", ATIVO, "| CONTA:", CONTA)
    print("MODO: SOMENTE LEITURA - NAO ENVIA ORDENS")
    print("PERIODOS:", TIMEFRAMES)
    print("-" * 60)

    for periodo in TIMEFRAMES:
        candles = dados_mercado[periodo]
        estado = estado_pernadas[periodo]

        if candles:
            preco = candles[-1]["close"]
            horario = time.strftime(
                "%H:%M:%S",
                time.localtime(candles[-1]["to"])
            )
        else:
            preco = "SEM DADOS"
            horario = "--:--:--"

        perna = (
            direcao_texto(estado["direcao"])
            if estado["direcao"]
            else "SEM PERNADA"
        )

        print(
            f"{periodo:>2}s | candles: {len(candles):>3} "
            f"| preco: {preco} | candle: {horario}"
        )
        print(
            "    PERNADA:",
            perna,
            "| desloc/ATR:",
            round(estado["deslocamento_atr"], 2),
            "| eficiencia:",
            round(estado["eficiencia"], 2)
        )

    print("-" * 60)
    print("SEQUENCIA ATUAL:")

    if sequencia["direcao"] is None:
        print("AGUARDANDO PRIMEIRO PADRAO OU PERNADA")
    else:
        print("DIRECAO:", direcao_texto(sequencia["direcao"]))

        for modulo in ("CRUZ", "FORCA", "FORMACAO", "PERNADA"):
            evento = sequencia["eventos"].get(modulo)

            if evento:
                print(
                    "[OK]", modulo,
                    "|", evento["periodo"], "s"
                )
            else:
                print("[...] ", modulo, "| AGUARDANDO")

        restante = VALIDADE_SEQUENCIA - (
            time.time() - sequencia["inicio"]
        )
        print("VALIDADE RESTANTE:", max(0, int(restante)), "s")

    print("-" * 60)
    print("ULTIMO SINAL:", ultimo_sinal)
    print("COMPRA: cruz alta + forca alta + soldados + perna alta")
    print("VENDA : cruz baixa + forca baixa + corvos + perna baixa")
    print("=" * 60)
    print("CTRL+C PARA ENCERRAR")


# ============================================================
# CONEXAO
# ============================================================

def conectar():
    print("\nConectando a IQ Option...")

    conectado, motivo = api.connect()

    if not conectado:
        raise RuntimeError(
            "Falha na conexao: " + str(motivo)
        )

    print("Conectado.")

    api.change_balance(CONTA)
    time.sleep(2)

    print("Conta selecionada:", CONTA)

    for periodo in TIMEFRAMES:
        api.start_candles_stream(
            ATIVO,
            periodo,
            QUANTIDADE_HISTORICO
        )
        time.sleep(0.5)

    print("Streams iniciados.")
    time.sleep(3)

    carregar_historico()

    # Inicializa as pernadas a partir do historico ja carregado.
    for periodo in TIMEFRAMES:
        atualizar_estado_pernadas(periodo)


# ============================================================
# LOOP PRINCIPAL
# ============================================================

def executar():
    conectar()

    print("\nQMS iniciado. Monitorando padroes e pernadas...")
    time.sleep(2)

    while True:
        for periodo in TIMEFRAMES:
            atualizar_candles(periodo)
            processar_periodo(periodo)

        verificar_expiracao()
        mostrar_painel()

        time.sleep(INTERVALO_ATUALIZACAO)


# ============================================================
# ENCERRAMENTO
# ============================================================

try:
    executar()

except KeyboardInterrupt:
    print("\nEncerramento solicitado pelo usuario.")

except Exception as erro:
    print("\nERRO NO QMS:")
    print(erro)
    traceback.print_exc()

finally:
    for periodo in TIMEFRAMES:
        try:
            api.stop_candles_stream(ATIVO, periodo)
        except Exception:
            pass

    try:
        api.close()
    except Exception:
        pass

    print("\nQMS ENCERRADO. NENHUMA ORDEM FOI ENVIADA.")
