# ============================================================
# QMS SWING TRADER H4 + CONTEXTO MN1/D1/W1 — TOPOS, FUNDOS E PERNADAS
# IQ OPTION / PYDROID 3
# SOMENTE LEITURA | SEM ORDENS AUTOMATICAS | SEM MARTINGALE
#
# Permite selecionar 12 padrões; escolhe o primeiro válido por candle fechado.
# O radar estrutural nao usa alertas antecipados: somente candles fechados.
#
# RSI, ADX/DI, ATR, EMAs e Momentum sao filtros de contexto/qualidade.
# Indicadores não geram sinal isoladamente: exigem padrão de candle confirmado.
# Analisa apenas candles reais fechados recebidos da API.
# Nao cria candles ou precos sinteticos e nao envia ordens.
# Leitura viva do preco real atualiza distancias/angulo; sinais so confirmam em candle fechado.
# Timeframe principal: H4 (4 horas), com contexto superior D1, W1 e MN1 (mensal).
# MN1 é agregado por mês-calendário a partir de candles D1 reais fechados da API;
# não são inventados preços: OHLC usa primeiro open, máximo/mínimo reais e último close do mês.
# ============================================================

import os
import time
import getpass
import json
from datetime import datetime

import numpy as np
import pandas as pd

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None

# ------------------------- CONFIGURACAO -------------------------
VERSAO = "QMS SWING TRADER H4 MN1 D1 W1 TOPOS FUNDOS + PERNADAS"
ATIVO = "EURUSD-OTC"
CONTA = "PRACTICE"

INTERVALO = 14400              # H4 = 4 horas
TIMEFRAME_LABEL = "H4"
INTERVALO_D1 = 86400
INTERVALO_W1 = 604800
CONTEXTO_SWING = {}
ULTIMA_ATUALIZACAO_CONTEXTO = 0
INTERVALO_MN1_FONTE = 86400  # MN1 usa candles D1 reais agregados por mês-calendário
MESES_MINIMOS_CONTEXTO = 30
QUANTIDADE_CANDLES = 400
MINIMO_CANDLES = 220
INTERVALO_LOOP = 30
MAX_FALHAS = 12

EMA_RAPIDA = 3
EMA_MEDIA = 30
EMA_TENDENCIA = 60
EMA_LONGA = 200
PERIODO_RSI = 14
PERIODO_ATR = 14
PERIODO_ADX = 14
PERIODO_MOMENTUM = 10

# Seletividade do padrao: flexivel, sem eliminar toda estrutura imperfeita
CORPO_MINIMO_FRACAO = 0.30
CORPO_MAXIMO_FRACAO = 0.98
SOBREPOSICAO_MAXIMA = 0.20
PAVIO_CONTRA_MAXIMO = 0.50
MAX_ESTICAMENTO_ATR = 3.2
ADX_MINIMO = 10.0
RSI_SOBRECOMPRA = 85.0
RSI_SOBREVENDA = 15.0
EXIGIR_CONTEXTO_EMA = False
EXIGIR_DI = False
COOLDOWN_SINAL = 14400        # evita repeticao de sinal dentro do mesmo candle H4

# Padrões habilitados inicialmente. O menu permite escolher quais monitorar
# ao iniciar; somente candles fechados podem confirmar qualquer padrão.
ORDEM_PADROES = [
    "Estrela da Manhã", "Estrela da Noite", "Engolfo de Alta", "Engolfo de Baixa",
    "Três Soldados", "Três Corvos", "Harami de Alta", "Harami de Baixa",
    "Impulso de Alta", "Impulso de Baixa", "Rompimento de mínima", "Rompimento de máxima",
]
PADROES_HABILITADOS = {nome: True for nome in ORDEM_PADROES}


def selecionar_padroes_interativo():
    """Permite habilitar/desabilitar padrões sem alterar os demais módulos."""
    global PADROES_HABILITADOS
    print("\nPADROES MONITORADOS — digite números separados por vírgula para alternar.")
    print("ENTER = manter todos os 12 habilitados. Digite A = habilitar todos.")
    for i, nome in enumerate(ORDEM_PADROES, 1):
        print(f"{i:2d}. [{'X' if PADROES_HABILITADOS.get(nome, False) else ' '}] {nome}")
    try:
        escolha = input("Seleção (ex.: 1,3,7) ou ENTER: ").strip()
    except (EOFError, KeyboardInterrupt):
        escolha = ""
    if escolha.upper() == "A":
        PADROES_HABILITADOS = {nome: True for nome in ORDEM_PADROES}
    elif escolha:
        novos = {nome: False for nome in ORDEM_PADROES}
        try:
            indices = {int(x.strip()) for x in escolha.split(",") if x.strip()}
            for idx in indices:
                if 1 <= idx <= len(ORDEM_PADROES):
                    novos[ORDEM_PADROES[idx - 1]] = True
            if any(novos.values()):
                PADROES_HABILITADOS = novos
            else:
                print("Seleção vazia/inválida; mantendo os padrões anteriormente habilitados.")
        except ValueError:
            print("Seleção inválida; mantendo os padrões anteriormente habilitados.")
    ativos = [n for n in ORDEM_PADROES if PADROES_HABILITADOS.get(n, False)]
    print("Padrões ativos: " + (", ".join(ativos) if ativos else "NENHUM — nenhum sinal será selecionado"))

# Fibonacci contextual calculada sobre 60 candles fechados (nao cria padroes nem sinais sozinho)
JANELA_FIBONACCI = 60  # calcula a Fibonacci usando exatamente os últimos 60 candles fechados
FIB_NIVEIS = (0.382, 0.500, 0.618, 0.786, 0.918)  # niveis Fibonacci adicionais
FIB_TOLERANCIA_ATR = 0.15
FIB_PIVOTO_LADO = 3  # pivô só é usado após confirmação por 3 candles à direita

ARQUIVO_HISTORICO = "qms_swing_h4_historico.csv"
ARQUIVO_PADROES = "qms_swing_h4_padroes.csv"

# Primeiro alvo provável: horizonte de 20 candles H4 (80 horas; cerca de 3,3 dias).
ALVO_HORIZONTE_CANDLES = 20
ALVO_ATR_BASE = 1.50
ALVO_INVALIDACAO_ATR = 1.00
ALVO_DISTANCIA_MIN_ATR = 0.35
ALVO_AMOSTRA_MINIMA = 30
ALVO_JANELA_HISTORICA = 2000
ARQUIVO_VALIDACAO_ALVOS = "qms_swing_h4_primeiro_alvo_validacao.csv"

# Persistencia adicional: candles reais, snapshots da janela Fibonacci de 60
# candles e pivôs Elliott confirmados. Os CSVs ficam na pasta deste script.
ARQUIVO_CANDLES_REAIS = "qms_swing_h4_candles_reais.csv"
ARQUIVO_JANELAS_60 = "qms_swing_h4_janelas_60_snapshot.csv"
ARQUIVO_PIVOS_ELLIOTT = "qms_swing_h4_pivos_elliott.csv"
ARQUIVO_TOPO_FUNDO = "qms_swing_h4_topos_fundos.csv"
ARQUIVO_RESULTADOS_SINAIS = "qms_swing_h4_sinais_resultados.csv"
ARQUIVO_ESTATISTICAS = "qms_swing_h4_estatisticas_contexto.csv"
ARQUIVO_ROMPIMENTOS_LATERAL = "qms_swing_h4_rompimentos_lateralizacao.csv"
PADRAO_DUPLO_TOLERANCIA_ATR = 0.35
# Margem absoluta mínima entre dois topos/fundos (EURUSD: 0.00010 = 1 pip).
# A tolerância efetiva é o maior valor entre esta margem e a fração do ATR.
PADRAO_DUPLO_TOLERANCIA_MINIMA_PRECO = 0.00010
# Permite comparar pivôs atuais com estruturas históricas de até 30 dias no modo swing.
PADRAO_DUPLO_LOOKBACK_HORAS = 720  # estruturas comparadas em janela de ate 30 dias
PADRAO_DUPLO_REJEICAO_ATR = 0.10
JANELA_LATERALIZACAO = 20
ROMPIMENTO_BUFFER_ATR = 0.05
# Projecao angular normalizada por ATR: diagnostico direcional, sem gerar ordem/sinal isoladamente.
ANGULAR_JANELAS = (5, 20, 60)
ANGULAR_LIMIAR_GRAUS = 5.0
ANGULAR_JANELA_PADRAO = 20
# False: angulo pontua a confluencia sem bloquear sozinho os padroes originais.
# True: exige alinhamento angular para aprovar sinal 3S3C.
ANGULAR_EXIGIR_ALINHAMENTO = False
VALIDACAO_HORIZONTE_CANDLES = 20
MAX_CANDLES_ANALISE = 3000  # histórico em memória para indicadores e backtest

API = None
ULTIMO_CANDLE = None
ULTIMO_ALERTA_ANTECIPADO = {}
ULTIMOS_SINAIS = {}
FALHAS_CONSECUTIVAS = 0
HISTORICO_CANDLES_CACHE = None
SNAPSHOTS_CARREGADOS = False
SNAPSHOTS_SALVOS = set()
PIVOS_CARREGADOS = False
PIVOS_SALVOS = set()
PADROES_DUPLOS_REGISTRADOS = set()
SINAIS_RESULTADOS_CARREGADOS = False
ULTIMO_CONTEXTO_DINAMICO = {}
ULTIMA_PERNADA_DINAMICA = {}
ULTIMA_LINHA_PRECO_DINAMICO = ""

RESET = "\033[0m"
VERDE = "\033[1;37;42m"
VERMELHO = "\033[1;37;41m"
AMARELO = "\033[1;30;43m"
AZUL = "\033[1;37;44m"
ROXO = "\033[1;37;45m"
CINZA = "\033[1;37;100m"


def cor(texto, codigo):
    return f"{codigo}{texto}{RESET}"


def fmt(valor, casas=5):
    try:
        valor = float(valor)
        return f"{valor:.{casas}f}" if np.isfinite(valor) else "N/D"
    except (TypeError, ValueError):
        return "N/D"


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
            "Biblioteca iqoptionapi ausente. Instale uma versao compativel no Pydroid 3."
        )
    email = input("E-mail da conta IQ Option: ").strip()
    senha = getpass.getpass("Senha: ")
    API = IQ_Option(email, senha)
    resultado = API.connect()
    conectado = resultado[0] if isinstance(resultado, tuple) else bool(resultado)
    if not conectado:
        raise RuntimeError(f"Falha na conexao: {resultado}")
    try:
        API.change_balance(CONTA)
    except Exception:
        pass
    print(f"Conectado | Conta solicitada: {CONTA}")
    print("SOMENTE LEITURA: nenhuma funcao de envio de ordem e usada.")


# -------------------- COLETA E VALIDACAO ------------------------
def validar_candles(df, minimo):
    obrigatorias = {"open", "close", "min", "max", "from", "to"}
    if df is None or not isinstance(df, pd.DataFrame):
        raise ValueError("Resposta de candles invalida.")
    if not obrigatorias.issubset(df.columns):
        raise ValueError("Campos OHLC/timestamps ausentes.")

    df = df.copy()
    for campo in obrigatorias:
        df[campo] = pd.to_numeric(df[campo], errors="coerce")

    df = df.dropna(subset=list(obrigatorias)).sort_values("from")
    df = df.drop_duplicates("from")

    if len(df) < minimo:
        raise ValueError(f"Dados insuficientes: {len(df)} candles; minimo {minimo}.")
    if (df[["open", "close", "min", "max"]] <= 0).any().any():
        raise ValueError("Precos invalidos ou nao positivos.")

    invalido = (
        (df["max"] < df["min"]) |
        (df["max"] < df["open"]) | (df["max"] < df["close"]) |
        (df["min"] > df["open"]) | (df["min"] > df["close"])
    )
    if invalido.any():
        raise ValueError("Candles OHLC inconsistentes.")

    return df.reset_index(drop=True)


def obter_candles(api, ativo, intervalo, quantidade):
    agora = time.time()
    dados = api.get_candles(ativo, intervalo, quantidade, agora)
    if not dados:
        raise ValueError(f"API nao retornou candles para {ativo}.")

    df = validar_candles(
        pd.DataFrame(dados),
        minimo=max(20, quantidade // 2)
    )

    # Usa apenas candles cujo fechamento ja ocorreu.
    df = df[df["to"] < agora].copy()
    if len(df) < MINIMO_CANDLES:
        raise ValueError(
            f"Candles H4 fechados insuficientes: {len(df)}; minimo {MINIMO_CANDLES}."
        )

    df = df.tail(quantidade).reset_index(drop=True)

    # Em H4, o mercado Forex pode ter intervalos maiores durante fins de semana/fechamentos.
    # Aceita somente lacunas que sejam multiplos do intervalo H4, sem inventar candles;
    # bloqueia timestamps desalinhados e lacunas extremas.
    amostra = df["from"].tail(31).to_numpy(dtype=float)
    dif = np.diff(amostra)
    if len(dif):
        multiplos = np.rint(dif / intervalo)
        alinhados = np.abs(dif - multiplos * intervalo) <= 3
        lacunas_ok = (multiplos >= 1) & (multiplos <= 18)
        if not np.all(alinhados & lacunas_ok):
            raise ValueError("Intervalo temporal H4 inconsistente ou lacuna excessiva. Analise bloqueada.")

    return df


# -------------------- HISTORICO PERSISTENTE ---------------------
def atualizar_historico_candles(df_atual):
    """
    Une candles fechados reais da API com o CSV persistente.
    A chave de deduplicação é ativo + timeframe + timestamp de abertura.
    O arquivo conserva todo o histórico; o DataFrame de trabalho usa a
    cauda MAX_CANDLES_ANALISE para manter o processamento controlado.
    """
    global HISTORICO_CANDLES_CACHE

    colunas = ["from", "to", "open", "max", "min", "close"]
    atual = df_atual[colunas].copy()
    for c in colunas:
        atual[c] = pd.to_numeric(atual[c], errors="coerce")
    atual = atual.dropna(subset=colunas)
    atual["from"] = atual["from"].astype("int64")
    atual["to"] = atual["to"].astype("int64")

    if HISTORICO_CANDLES_CACHE is None:
        if os.path.exists(ARQUIVO_CANDLES_REAIS):
            try:
                salvo = pd.read_csv(ARQUIVO_CANDLES_REAIS)
                obrig = {"ativo", "timeframe", *colunas}
                if obrig.issubset(salvo.columns):
                    salvo = salvo[
                        (salvo["ativo"].astype(str) == str(ATIVO)) &
                        (salvo["timeframe"].astype(str) == TIMEFRAME_LABEL)
                    ].copy()
                    for c in colunas:
                        salvo[c] = pd.to_numeric(salvo[c], errors="coerce")
                    salvo = salvo.dropna(subset=colunas)
                    HISTORICO_CANDLES_CACHE = salvo[colunas].copy()
                else:
                    HISTORICO_CANDLES_CACHE = pd.DataFrame(columns=colunas)
            except Exception as erro:
                print(f"Aviso: histórico CSV não pôde ser lido ({erro}); iniciando cache com dados atuais.")
                HISTORICO_CANDLES_CACHE = pd.DataFrame(columns=colunas)
        else:
            # Migra o histórico antigo do próprio QMS, caso exista, para que os
            # registros anteriores também participem da análise combinada.
            HISTORICO_CANDLES_CACHE = pd.DataFrame(columns=colunas)
            if os.path.exists(ARQUIVO_HISTORICO):
                try:
                    legado = pd.read_csv(ARQUIVO_HISTORICO)
                    obrig_legado = {
                        "ativo", "timeframe", "timestamp_candle_fechado",
                        "open", "close"
                    }
                    if obrig_legado.issubset(legado.columns):
                        legado = legado[
                            (legado["ativo"].astype(str) == str(ATIVO)) &
                            (legado["timeframe"].astype(str) == TIMEFRAME_LABEL)
                        ].copy()
                        if "high" in legado.columns:
                            legado["max"] = legado["high"]
                        elif "max" not in legado.columns:
                            legado["max"] = np.nan
                        if "low" in legado.columns:
                            legado["min"] = legado["low"]
                        elif "min" not in legado.columns:
                            legado["min"] = np.nan
                        legado["to"] = pd.to_numeric(
                            legado["timestamp_candle_fechado"], errors="coerce"
                        )
                        legado["from"] = legado["to"] - INTERVALO
                        for c in colunas:
                            legado[c] = pd.to_numeric(legado[c], errors="coerce")
                        legado = legado.dropna(subset=colunas)
                        HISTORICO_CANDLES_CACHE = legado[colunas].drop_duplicates(
                            "from", keep="last"
                        ).sort_values("from").reset_index(drop=True)
                        if not HISTORICO_CANDLES_CACHE.empty:
                            migrado = HISTORICO_CANDLES_CACHE.copy()
                            migrado.insert(0, "timeframe", TIMEFRAME_LABEL)
                            migrado.insert(0, "ativo", ATIVO)
                            migrado["horario_captura"] = datetime.now().isoformat(timespec="seconds")
                            migrado.to_csv(
                                ARQUIVO_CANDLES_REAIS, index=False
                            )
                except Exception as erro:
                    print(f"Aviso: histórico anterior não foi migrado ({erro}).")

    conhecidos = set(
        pd.to_numeric(HISTORICO_CANDLES_CACHE["from"], errors="coerce")
        .dropna().astype("int64").tolist()
    ) if not HISTORICO_CANDLES_CACHE.empty else set()
    novos = atual[~atual["from"].isin(conhecidos)].copy()

    if not novos.empty:
        reg = novos.copy()
        reg.insert(0, "timeframe", TIMEFRAME_LABEL)
        reg.insert(0, "ativo", ATIVO)
        reg["horario_captura"] = datetime.now().isoformat(timespec="seconds")
        existe = os.path.exists(ARQUIVO_CANDLES_REAIS)
        reg.to_csv(ARQUIVO_CANDLES_REAIS, mode="a", header=not existe, index=False)

    HISTORICO_CANDLES_CACHE = pd.concat(
        [HISTORICO_CANDLES_CACHE, novos[colunas]], ignore_index=True
    )
    HISTORICO_CANDLES_CACHE = (
        HISTORICO_CANDLES_CACHE.drop_duplicates("from", keep="last")
        .sort_values("from").reset_index(drop=True)
    )

    combinado = pd.concat(
        [HISTORICO_CANDLES_CACHE, atual], ignore_index=True
    ).drop_duplicates("from", keep="last").sort_values("from").reset_index(drop=True)

    # Revalida o OHLC combinado antes de qualquer análise.
    combinado = validar_candles(combinado, minimo=MINIMO_CANDLES)
    agora = time.time()
    combinado = combinado[combinado["to"] < agora].copy()
    if len(combinado) < MINIMO_CANDLES:
        raise ValueError("Histórico combinado não tem candles fechados suficientes.")
    return combinado.tail(MAX_CANDLES_ANALISE).reset_index(drop=True)


def salvar_snapshot_janela_60(df):
    """
    Grava uma fotografia por candle fechado, contendo a janela real completa
    de 60 candles e os indicadores/Fibonacci calculados naquele momento.
    O OHLC também fica no CSV mestre, sem duplicação no histórico principal.
    """
    global SNAPSHOTS_CARREGADOS, SNAPSHOTS_SALVOS
    if df is None or len(df) < JANELA_FIBONACCI:
        return

    timestamp = int(df.iloc[-1]["to"])
    chave = (str(ATIVO), TIMEFRAME_LABEL, timestamp)
    if not SNAPSHOTS_CARREGADOS:
        if os.path.exists(ARQUIVO_JANELAS_60):
            try:
                old = pd.read_csv(
                    ARQUIVO_JANELAS_60,
                    usecols=["ativo", "timeframe", "snapshot_timestamp"]
                )
                SNAPSHOTS_SALVOS = set(
                    (str(r.ativo), str(r.timeframe), int(r.snapshot_timestamp))
                    for r in old.itertuples(index=False)
                    if pd.notna(r.snapshot_timestamp)
                )
            except Exception:
                SNAPSHOTS_SALVOS = set()
        SNAPSHOTS_CARREGADOS = True
    if chave in SNAPSHOTS_SALVOS:
        return

    janela = df.tail(JANELA_FIBONACCI).copy()
    campos = [
        "from", "to", "open", "max", "min", "close",
        "ema3", "ema30", "ema60", "ema200", "rsi", "atr", "adx",
        "di_positivo", "di_negativo", "momentum", "fib_topo", "fib_fundo",
        "fib_amplitude", "fib_382", "fib_500", "fib_618", "fib_786",
        "fib_918", "fib_direcao"
    ]
    campos = [c for c in campos if c in janela.columns]
    registros = []
    for _, r in janela[campos].iterrows():
        item = {}
        for c in campos:
            v = r[c]
            if pd.isna(v):
                item[c] = None
            elif c in ("from", "to"):
                item[c] = int(v)
            elif c == "fib_direcao":
                item[c] = str(v)
            else:
                item[c] = float(v)
        registros.append(item)

    a = df.iloc[-1]
    reg = {
        "ativo": ATIVO,
        "timeframe": TIMEFRAME_LABEL,
        "snapshot_timestamp": timestamp,
        "snapshot_horario": datetime.fromtimestamp(timestamp).isoformat(timespec="seconds"),
        "quantidade_candles_janela": len(janela),
        "inicio_timestamp": int(janela.iloc[0]["from"]),
        "fim_timestamp": int(janela.iloc[-1]["to"]),
        "janela_60_dados_json": json.dumps(registros, separators=(",", ":"), ensure_ascii=False),
        "ema_rapida_param": EMA_RAPIDA,
        "ema_media_param": EMA_MEDIA,
        "ema_tendencia_param": EMA_TENDENCIA,
        "ema_longa_param": EMA_LONGA,
        "rsi_periodo_param": PERIODO_RSI,
        "atr_periodo_param": PERIODO_ATR,
        "adx_periodo_param": PERIODO_ADX,
        "momentum_periodo_param": PERIODO_MOMENTUM,
        "fib_janela_param": JANELA_FIBONACCI,
        "fib_pivoto_lado_param": FIB_PIVOTO_LADO,
        "fib_topo": a.get("fib_topo", np.nan),
        "fib_fundo": a.get("fib_fundo", np.nan),
        "fib_382": a.get("fib_382", np.nan),
        "fib_500": a.get("fib_500", np.nan),
        "fib_618": a.get("fib_618", np.nan),
        "fib_786": a.get("fib_786", np.nan),
        "fib_918": a.get("fib_918", np.nan),
        "fib_direcao": a.get("fib_direcao", "N/D"),
    }
    existe = os.path.exists(ARQUIVO_JANELAS_60)
    pd.DataFrame([reg]).to_csv(
        ARQUIVO_JANELAS_60, mode="a", header=not existe, index=False
    )
    SNAPSHOTS_SALVOS.add(chave)


def salvar_pivos_elliott(df):
    """Persiste pivôs confirmados com preço, horário do pivô e confirmação."""
    global PIVOS_CARREGADOS, PIVOS_SALVOS
    lado = FIB_PIVOTO_LADO
    if df is None or len(df) < lado * 2 + 3:
        return

    if not PIVOS_CARREGADOS:
        if os.path.exists(ARQUIVO_PIVOS_ELLIOTT):
            try:
                old = pd.read_csv(
                    ARQUIVO_PIVOS_ELLIOTT,
                    usecols=["ativo", "timeframe", "timestamp_pivo", "tipo"]
                )
                PIVOS_SALVOS = set(
                    (str(r.ativo), str(r.timeframe), int(r.timestamp_pivo), str(r.tipo))
                    for r in old.itertuples(index=False)
                    if pd.notna(r.timestamp_pivo)
                )
            except Exception:
                PIVOS_SALVOS = set()
        PIVOS_CARREGADOS = True

    highs = df["max"].to_numpy(dtype=float)
    lows = df["min"].to_numpy(dtype=float)
    rows = []
    fim = len(df) - lado
    for j in range(lado, fim):
        ini, fim_j = j - lado, j + lado + 1
        wh, wl = highs[ini:fim_j], lows[ini:fim_j]
        encontrados = []
        if highs[j] >= np.max(wh) and np.count_nonzero(wh == highs[j]) == 1:
            encontrados.append(("H", float(highs[j])))
        if lows[j] <= np.min(wl) and np.count_nonzero(wl == lows[j]) == 1:
            encontrados.append(("L", float(lows[j])))
        for tipo, preco in encontrados:
            ts = int(df.iloc[j]["from"])
            chave = (str(ATIVO), TIMEFRAME_LABEL, ts, tipo)
            if chave in PIVOS_SALVOS:
                continue
            rows.append({
                "ativo": ATIVO, "timeframe": TIMEFRAME_LABEL,
                "timestamp_pivo": ts, "horario_pivo": datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                "tipo": tipo, "preco": preco,
                "timestamp_confirmacao": int(df.iloc[j + lado]["to"]),
                "lado_confirmacao": lado,
                "nota": "Pivô confirmado somente após candles fechados à direita."
            })
            PIVOS_SALVOS.add(chave)
    if rows:
        existe = os.path.exists(ARQUIVO_PIVOS_ELLIOTT)
        pd.DataFrame(rows).to_csv(
            ARQUIVO_PIVOS_ELLIOTT, mode="a", header=not existe, index=False
        )



# ------------------ ESTRUTURA: TOPOS/FUNDOS DUPLOS ------------------
def _pivos_confirmados(df, janela=60):
    """Retorna pivôs confirmados usando apenas candles fechados e lado direito disponível."""
    lado = FIB_PIVOTO_LADO
    base = df.tail(max(janela, lado * 2 + 5)).reset_index(drop=True)
    if len(base) < lado * 2 + 3:
        return []
    highs = base["max"].to_numpy(dtype=float)
    lows = base["min"].to_numpy(dtype=float)
    pivots = []
    for j in range(lado, len(base) - lado):
        wh, wl = highs[j-lado:j+lado+1], lows[j-lado:j+lado+1]
        if highs[j] == np.max(wh) and np.count_nonzero(wh == highs[j]) == 1:
            pivots.append({"idx": j, "tipo": "H", "preco": float(highs[j]),
                           "timestamp": int(base.iloc[j]["from"]),
                           "confirmacao": int(base.iloc[j+lado]["to"])})
        if lows[j] == np.min(wl) and np.count_nonzero(wl == lows[j]) == 1:
            pivots.append({"idx": j, "tipo": "L", "preco": float(lows[j]),
                           "timestamp": int(base.iloc[j]["from"]),
                           "confirmacao": int(base.iloc[j+lado]["to"])})
    pivots.sort(key=lambda x: (x["idx"], x["tipo"]))
    compact=[]
    for pv in pivots:
        if compact and compact[-1]["tipo"] == pv["tipo"]:
            old=compact[-1]
            extreme = pv["preco"] > old["preco"] if pv["tipo"] == "H" else pv["preco"] < old["preco"]
            if extreme:
                compact[-1]=pv
        else:
            compact.append(pv)
    return compact


def detectar_topo_fundo_duplo(df, elliott=None, fibonacci=None):
    """Radar de topo/fundo duplo com margem mínima e pivôs históricos persistidos.

    Compara pivôs confirmados do candle atual com pivôs reais registrados anteriormente,
    dentro da janela histórica configurada. O sinal só confirma após fechamento além
    da linha de pescoço; a proximidade por si só nunca é tratada como confirmação.
    """
    vazio = {"detectado": False, "nome": "NENHUM", "direcao": "NENHUMA", "estado": "SEM_PADRAO"}
    if df is None or len(df) < max(JANELA_FIBONACCI, 20):
        return {**vazio, "estado": "DADOS_INSUFICIENTES"}
    a = df.iloc[-1]
    atr = float(a.get("atr", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return {**vazio, "estado": "ATR_INDISPONIVEL"}

    agora = int(a.get("to", a.get("from", 0)))
    limite_historico = agora - int(PADRAO_DUPLO_LOOKBACK_HORAS * 3600)
    pivots = []

    # Pivôs detectados na série real atual.
    for pv in _pivos_confirmados(df, MAX_CANDLES_ANALISE):
        pivots.append({**pv, "origem": "CANDLES_ATUAIS"})

    # Pivôs guardados em CSV permitem procurar estruturas que ocorreram há minutos/horas,
    # mesmo que já tenham saído da janela de candles carregada pela API.
    if os.path.exists(ARQUIVO_PIVOS_ELLIOTT):
        try:
            hist = pd.read_csv(ARQUIVO_PIVOS_ELLIOTT)
            obrigatorias = {"ativo", "timeframe", "timestamp_pivo", "timestamp_confirmacao", "tipo", "preco"}
            if obrigatorias.issubset(hist.columns):
                hist = hist[(hist["ativo"].astype(str) == str(ATIVO)) &
                            (hist["timeframe"].astype(str) == TIMEFRAME_LABEL)]
                hist = hist[pd.to_numeric(hist["timestamp_pivo"], errors="coerce") >= limite_historico]
                for r in hist.itertuples(index=False):
                    try:
                        pivots.append({
                            "idx": -1, "tipo": str(r.tipo), "preco": float(r.preco),
                            "timestamp": int(r.timestamp_pivo),
                            "confirmacao": int(r.timestamp_confirmacao), "origem": "HISTORICO_CSV"
                        })
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass

    # Deduplica pivôs repetidos entre memória e CSV; mantém somente os confirmados
    # e dentro da janela histórica configurada.
    unicos = {}
    for pv in pivots:
        ts = int(pv.get("timestamp", 0))
        conf = int(pv.get("confirmacao", 0))
        if ts < limite_historico or conf > agora or conf <= 0:
            continue
        chave = (ts, str(pv.get("tipo")))
        unicos[chave] = pv
    piv = sorted(unicos.values(), key=lambda x: (int(x["timestamp"]), str(x["tipo"])))

    # Compacta pivôs consecutivos do mesmo tipo, preservando o extremo mais relevante.
    compact = []
    for pv in piv:
        if compact and compact[-1]["tipo"] == pv["tipo"]:
            anterior = compact[-1]
            extremo = (pv["preco"] > anterior["preco"] if pv["tipo"] == "H"
                       else pv["preco"] < anterior["preco"])
            if extremo:
                compact[-1] = pv
        else:
            compact.append(pv)
    if len(compact) < 3:
        return {**vazio, "estado": "AGUARDANDO_PIVOS_HISTORICOS", "pivos": len(compact),
                "lookback_horas": PADRAO_DUPLO_LOOKBACK_HORAS}

    # A margem mínima é absoluta; em volatilidade maior, prevalece 0.35 ATR.
    tol = max(atr * PADRAO_DUPLO_TOLERANCIA_ATR,
              float(PADRAO_DUPLO_TOLERANCIA_MINIMA_PRECO), 1e-12)
    buffer = atr * ROMPIMENTO_BUFFER_ATR
    close = float(a["close"])
    op = float(a["open"])
    prev_close = float(df.iloc[-2]["close"])
    p1, neck, p2 = compact[-3:]
    tipos = [p1["tipo"], neck["tipo"], p2["tipo"]]
    common = {"detectado": False, "nome": "NENHUM", "direcao": "NENHUMA",
              "estado": "SEM_PADRAO", "pivos": len(compact), "tolerancia_preco": tol,
              "tolerancia_atr": atr * PADRAO_DUPLO_TOLERANCIA_ATR,
              "tolerancia_minima_preco": PADRAO_DUPLO_TOLERANCIA_MINIMA_PRECO,
              "lookback_horas": PADRAO_DUPLO_LOOKBACK_HORAS,
              "atr": atr, "elliott_estado": (elliott or {}).get("estado", "N/D"),
              "elliott_direcao": (elliott or {}).get("direcao", "N/D"),
              "fib_direcao": (fibonacci or {}).get("direcao", a.get("fib_direcao", "N/D"))}

    if tipos == ["H", "L", "H"]:
        distancia = abs(p2["preco"] - p1["preco"])
        if distancia > tol:
            return {**common, "estado": "TOPO_DUPLO_FORA_DA_MARGEM",
                    "pivo1_preco": p1["preco"], "pivo2_preco": p2["preco"],
                    "distancia_pivos": distancia}
        neck_price = float(neck["preco"])
        rompeu_agora = close < neck_price - buffer and prev_close >= neck_price - buffer
        if not rompeu_agora:
            return {**common, "estado": "TOPO_DUPLO_POTENCIAL_AGUARDANDO_ROMPIMENTO",
                    "nome": "TOPO_DUPLO", "direcao": "PUT", "linha_pescoco": neck_price,
                    "pivo1_timestamp": p1["timestamp"], "pivo1_preco": p1["preco"],
                    "pivo2_timestamp": p2["timestamp"], "pivo2_preco": p2["preco"],
                    "distancia_pivos": distancia, "distancia_pivos_atr": distancia / atr}
        return {**common, "detectado": True, "nome": "TOPO_DUPLO", "direcao": "PUT",
                "estado": "CONFIRMADO_ROMPIMENTO_PESCOCO", "timestamp_sinal": int(a["to"]),
                "preco_sinal": close, "pivo1_timestamp": p1["timestamp"],
                "pivo1_preco": p1["preco"], "pivo2_timestamp": p2["timestamp"],
                "pivo2_preco": p2["preco"], "pivo2_confirmacao": p2["confirmacao"],
                "pivo_intermediario_timestamp": neck["timestamp"], "linha_pescoco": neck_price,
                "distancia_pivos": distancia, "distancia_pivos_atr": distancia / atr,
                "rejeicao": close < op, "rompimento_pescoco": True,
                "alvo_teorico": neck_price - (max(p1["preco"], p2["preco"]) - neck_price),
                "observacao": "Topo duplo confirmado por fechamento abaixo da linha de pescoco; nao garante continuidade."}

    if tipos == ["L", "H", "L"]:
        distancia = abs(p2["preco"] - p1["preco"])
        if distancia > tol:
            return {**common, "estado": "FUNDO_DUPLO_FORA_DA_MARGEM",
                    "pivo1_preco": p1["preco"], "pivo2_preco": p2["preco"],
                    "distancia_pivos": distancia}
        neck_price = float(neck["preco"])
        rompeu_agora = close > neck_price + buffer and prev_close <= neck_price + buffer
        if not rompeu_agora:
            return {**common, "estado": "FUNDO_DUPLO_POTENCIAL_AGUARDANDO_ROMPIMENTO",
                    "nome": "FUNDO_DUPLO", "direcao": "CALL", "linha_pescoco": neck_price,
                    "pivo1_timestamp": p1["timestamp"], "pivo1_preco": p1["preco"],
                    "pivo2_timestamp": p2["timestamp"], "pivo2_preco": p2["preco"],
                    "distancia_pivos": distancia, "distancia_pivos_atr": distancia / atr}
        return {**common, "detectado": True, "nome": "FUNDO_DUPLO", "direcao": "CALL",
                "estado": "CONFIRMADO_ROMPIMENTO_PESCOCO", "timestamp_sinal": int(a["to"]),
                "preco_sinal": close, "pivo1_timestamp": p1["timestamp"],
                "pivo1_preco": p1["preco"], "pivo2_timestamp": p2["timestamp"],
                "pivo2_preco": p2["preco"], "pivo2_confirmacao": p2["confirmacao"],
                "pivo_intermediario_timestamp": neck["timestamp"], "linha_pescoco": neck_price,
                "distancia_pivos": distancia, "distancia_pivos_atr": distancia / atr,
                "rejeicao": close > op, "rompimento_pescoco": True,
                "alvo_teorico": neck_price + (neck_price - min(p1["preco"], p2["preco"])),
                "observacao": "Fundo duplo confirmado por fechamento acima da linha de pescoco; nao garante continuidade."}
    return {**common, "estado": "SEM_SEQUENCIA_DUPLA_RECENTE"}


def detectar_rompimento_lateralizacao(df, padrao_duplo=None):
    """Confirma rompimento da faixa lateral apenas no fechamento do candle.

    Se houver topo/fundo duplo reconhecido mas ainda aguardando a linha de pescoco,
    não gera sinal genérico contra essa estrutura: espera sua confirmação específica.
    """
    vazio = {"detectado": False, "nome": "ROMPIMENTO_LATERALIZACAO", "direcao": "NENHUMA",
             "estado": "SEM_ROMPIMENTO_CONFIRMADO"}
    estado_duplo = str((padrao_duplo or {}).get("estado", ""))
    if estado_duplo in ("TOPO_DUPLO_AGUARDANDO_FECHAMENTO_ABAIXO", "FUNDO_DUPLO_AGUARDANDO_FECHAMENTO_ACIMA"):
        return {**vazio, "estado": estado_duplo, "bloqueado_aguardando_padrao_duplo": True,
                "linha_pescoco": (padrao_duplo or {}).get("linha_pescoco")}
    if df is None or len(df) < JANELA_LATERALIZACAO + 2:
        return {**vazio, "estado": "DADOS_INSUFICIENTES"}
    a = df.iloc[-1]
    atr = float(a.get("atr", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return {**vazio, "estado": "ATR_INDISPONIVEL"}
    # A faixa usa somente os candles anteriores; o candle de confirmação fica fora do cálculo.
    base = df.iloc[-(JANELA_LATERALIZACAO + 1):-1]
    topo = float(base["max"].max())
    fundo = float(base["min"].min())
    close = float(a["close"])
    anterior = float(df.iloc[-2]["close"])
    margem = atr * ROMPIMENTO_BUFFER_ATR
    acima = close > topo + margem and anterior <= topo + margem
    abaixo = close < fundo - margem and anterior >= fundo - margem
    if acima:
        return {**vazio, "detectado": True, "direcao": "CALL", "estado": "ROMPIMENTO_FAIXA_CONFIRMADO",
                "timestamp_sinal": int(a["to"]), "preco_sinal": close, "limite_superior": topo,
                "limite_inferior": fundo, "atr": atr, "buffer": margem,
                "observacao": "CALL candidato por fechamento confirmado acima da faixa lateral."}
    if abaixo:
        return {**vazio, "detectado": True, "direcao": "PUT", "estado": "ROMPIMENTO_FAIXA_CONFIRMADO",
                "timestamp_sinal": int(a["to"]), "preco_sinal": close, "limite_superior": topo,
                "limite_inferior": fundo, "atr": atr, "buffer": margem,
                "observacao": "PUT candidato por fechamento confirmado abaixo da faixa lateral."}
    return {**vazio, "limite_superior": topo, "limite_inferior": fundo, "atr": atr,
            "buffer": margem, "observacao": "Aguardando fechamento fora dos limites da faixa."}


def registrar_padrao_duplo(padrao, elliott=None, fibonacci=None):
    """Grava cada estrutura uma vez; não cria ordens nem modifica o sinal 3S3C original."""
    global PADROES_DUPLOS_REGISTRADOS
    if not padrao or not padrao.get("detectado"):
        return
    if not PADROES_DUPLOS_REGISTRADOS and os.path.exists(ARQUIVO_TOPO_FUNDO):
        try:
            old=pd.read_csv(ARQUIVO_TOPO_FUNDO,usecols=["ativo","timeframe","nome","pivo1_timestamp","pivo2_timestamp"])
            PADROES_DUPLOS_REGISTRADOS=set((str(r.ativo),str(r.timeframe),str(r.nome),int(r.pivo1_timestamp),int(r.pivo2_timestamp)) for r in old.itertuples(index=False))
        except Exception:
            PADROES_DUPLOS_REGISTRADOS=set()
    key=(str(ATIVO),TIMEFRAME_LABEL,str(padrao.get("nome")),int(padrao.get("pivo1_timestamp",0)),int(padrao.get("pivo2_timestamp",0)))
    if key in PADROES_DUPLOS_REGISTRADOS:
        return
    reg={"ativo":ATIVO,"timeframe":TIMEFRAME_LABEL,"nome":padrao.get("nome"),"direcao":padrao.get("direcao"),
         "estado":padrao.get("estado"),"timestamp_sinal":padrao.get("timestamp_sinal"),
         "horario_sinal":datetime.fromtimestamp(int(padrao.get("timestamp_sinal",time.time()))).isoformat(timespec="seconds"),
         "preco_sinal":padrao.get("preco_sinal"),"pivo1_timestamp":padrao.get("pivo1_timestamp"),
         "pivo1_preco":padrao.get("pivo1_preco"),"pivo2_timestamp":padrao.get("pivo2_timestamp"),
         "pivo2_preco":padrao.get("pivo2_preco"),"pivo2_confirmacao":padrao.get("pivo2_confirmacao"),
         "pivo_intermediario_timestamp":padrao.get("pivo_intermediario_timestamp"),"linha_pescoco":padrao.get("linha_pescoco"),
         "distancia_pivos":padrao.get("distancia_pivos"),"distancia_pivos_atr":padrao.get("distancia_pivos_atr"),
         "tolerancia_preco":padrao.get("tolerancia_preco"),"atr":padrao.get("atr"),"rejeicao":padrao.get("rejeicao"),
         "rompimento_pescoco":padrao.get("rompimento_pescoco"),"alvo_teorico":padrao.get("alvo_teorico"),
         "elliott_estado":(elliott or {}).get("estado","N/D"),"elliott_direcao":(elliott or {}).get("direcao","N/D"),
         "elliott_contagem":(elliott or {}).get("contagem","N/D"),"elliott_confianca":(elliott or {}).get("confianca","N/D"),
         "fib_direcao":str((fibonacci or {}).get("direcao","N/D")),"observacao":padrao.get("observacao","")}
    exists=os.path.exists(ARQUIVO_TOPO_FUNDO)
    pd.DataFrame([reg]).to_csv(ARQUIVO_TOPO_FUNDO,mode="a",header=not exists,index=False)
    PADROES_DUPLOS_REGISTRADOS.add(key)
    registrar_sinal_resultado(padrao)


def registrar_sinal_resultado(padrao):
    """Guarda candidato para validação futura com candles reais fechados."""
    if not padrao or not padrao.get("detectado"):
        return
    arquivo=ARQUIVO_RESULTADOS_SINAIS
    cols=["ativo","timeframe","padrao","direcao","timestamp_sinal","preco_sinal","horizonte_candles","status_validacao","max_favoravel","max_contrario","resultado_atr","timestamp_validacao"]
    row={"ativo":ATIVO,"timeframe":TIMEFRAME_LABEL,"padrao":padrao.get("nome"),"direcao":padrao.get("direcao"),
         "timestamp_sinal":int(padrao.get("timestamp_sinal",0)),"preco_sinal":float(padrao.get("preco_sinal",np.nan)),
         "horizonte_candles":VALIDACAO_HORIZONTE_CANDLES,"status_validacao":"PENDENTE",
         "max_favoravel":np.nan,"max_contrario":np.nan,"resultado_atr":np.nan,"timestamp_validacao":np.nan}
    if os.path.exists(arquivo):
        try:
            old=pd.read_csv(arquivo)
            if "timestamp_sinal" in old and ((old["ativo"].astype(str)==ATIVO)&(old["padrao"].astype(str)==str(row["padrao"]))&(pd.to_numeric(old["timestamp_sinal"],errors="coerce")==row["timestamp_sinal"])).any():
                return
            old=pd.concat([old,pd.DataFrame([row])],ignore_index=True)
            old.to_csv(arquivo,index=False)
            return
        except Exception:
            pass
    pd.DataFrame([row],columns=cols).to_csv(arquivo,index=False)


def atualizar_resultados_sinais(df):
    """Fecha validação somente quando já existem 20 candles posteriores fechados."""
    if not os.path.exists(ARQUIVO_RESULTADOS_SINAIS):
        return {"resolvidos":0,"acertos":0,"amostras":0,"taxa":np.nan}
    try:
        hist=pd.read_csv(ARQUIVO_RESULTADOS_SINAIS)
        if hist.empty or "timestamp_sinal" not in hist:
            return {"resolvidos":0,"acertos":0,"amostras":0,"taxa":np.nan}
        closes=df["close"].to_numpy(float); highs=df["max"].to_numpy(float); lows=df["min"].to_numpy(float); times=df["to"].to_numpy(float)
        latest_ts=int(times[-1]); updated=0
        for ix,row in hist.iterrows():
            if str(row.get("ativo"))!=ATIVO or str(row.get("timeframe"))!=TIMEFRAME_LABEL or str(row.get("status_validacao"))!="PENDENTE":
                continue
            ts=pd.to_numeric(row.get("timestamp_sinal"),errors="coerce")
            if pd.isna(ts): continue
            hits=np.where(times==float(ts))[0]
            if not len(hits):
                hits=np.where(times>=float(ts))[0]
                if not len(hits): continue
                i=int(hits[0])
            else: i=int(hits[-1])
            fim=i+int(row.get("horizonte_candles",VALIDACAO_HORIZONTE_CANDLES))
            if fim>=len(df): continue
            entry=float(row.get("preco_sinal",closes[i])); direction=str(row.get("direcao")); future_high=highs[i+1:fim+1]; future_low=lows[i+1:fim+1]
            if not len(future_high): continue
            if direction=="CALL": fav=float(np.max(future_high)-entry); adv=float(entry-np.min(future_low))
            else: fav=float(entry-np.min(future_low)); adv=float(np.max(future_high)-entry)
            # Resultado descritivo de excursão, não é payout nem promessa de acerto.
            hist.loc[ix,"max_favoravel"]=fav; hist.loc[ix,"max_contrario"]=adv
            hist.loc[ix,"resultado_atr"]=(fav/float(df.iloc[i].get("atr",np.nan))) if i<len(df) and float(df.iloc[i].get("atr",np.nan) or 0)>0 else np.nan
            hist.loc[ix,"status_validacao"]="VALIDADO_20_CANDLES"; hist.loc[ix,"timestamp_validacao"]=latest_ts; updated+=1
        hist.to_csv(ARQUIVO_RESULTADOS_SINAIS,index=False)
        resolved=hist[(hist["ativo"].astype(str)==ATIVO)&(hist["timeframe"].astype(str)==TIMEFRAME_LABEL)&(hist["status_validacao"].astype(str)=="VALIDADO_20_CANDLES")].copy()
        # sucesso direcional descritivo: excursão favorável maior que a contrária no horizonte.
        if len(resolved):
            fav=pd.to_numeric(resolved["max_favoravel"],errors="coerce"); adv=pd.to_numeric(resolved["max_contrario"],errors="coerce")
            acc=int((fav>adv).sum()); n=int((fav.notna()&adv.notna()).sum()); rate=(100.0*acc/n) if n else np.nan
        else: acc=n=0; rate=np.nan
        stats={"ativo":ATIVO,"timeframe":TIMEFRAME_LABEL,"timestamp_calculo":latest_ts,"amostras_validadas":n,"favoravel_maior_que_contrario":acc,"taxa_descritiva_pct":rate,"horizonte_candles":VALIDACAO_HORIZONTE_CANDLES,"nota":"Taxa descritiva de excursao; nao equivale a probabilidade de lucro."}
        exists=os.path.exists(ARQUIVO_ESTATISTICAS)
        pd.DataFrame([stats]).to_csv(ARQUIVO_ESTATISTICAS,mode="a",header=not exists,index=False)
        return {"resolvidos":updated,"acertos":acc,"amostras":n,"taxa":rate}
    except Exception:
        return {"resolvidos":0,"acertos":0,"amostras":0,"taxa":np.nan}


# ------------------------- INDICADORES --------------------------
def calcular_rsi(close, periodo=14):
    delta = close.diff()
    ganhos = delta.clip(lower=0)
    perdas = -delta.clip(upper=0)
    mg = ganhos.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    mp = perdas.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    rs = mg / mp.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.mask((mp == 0) & (mg > 0), 100)
    return rsi.mask((mp == 0) & (mg == 0), 50)


def calcular_projecao_angular(df):
    """Estima direcao por inclinacao linear em multiplas janelas de candles fechados.

    O angulo e normalizado pela ATR por candle para reduzir a dependencia da escala
    do ativo. Nao e um angulo geometrico absoluto do grafico nem uma garantia futura.
    Usa apenas dados fechados presentes no dataframe.
    """
    resultado = {
        "estado": "DADOS_INSUFICIENTES", "direcao": "N/D",
        "angulos": {}, "inclinacoes_atr": {}, "alinhamento": "N/D",
        "janela_principal": ANGULAR_JANELA_PADRAO,
        "limiar_graus": ANGULAR_LIMIAR_GRAUS,
    }
    if df is None or "close" not in df.columns:
        return resultado
    close = pd.to_numeric(df["close"], errors="coerce").dropna().to_numpy(dtype=float)
    if len(close) < max(ANGULAR_JANELAS):
        return resultado
    atr_val = np.nan
    if "atr" in df.columns:
        try:
            atr_val = float(pd.to_numeric(df["atr"], errors="coerce").iloc[-1])
        except (TypeError, ValueError, IndexError):
            pass
    if not np.isfinite(atr_val) or atr_val <= 0:
        return {**resultado, "estado": "ATR_INDISPONIVEL"}

    angulos = {}
    inclinacoes = {}
    for janela in ANGULAR_JANELAS:
        y = close[-janela:]
        x = np.arange(janela, dtype=float)
        slope = float(np.polyfit(x, y, 1)[0])
        normalizada = slope / atr_val
        angulo = float(np.degrees(np.arctan(normalizada)))
        nome = str(janela)
        angulos[nome] = angulo
        inclinacoes[nome] = normalizada

    dirs = []
    for janela in ANGULAR_JANELAS:
        a = angulos[str(janela)]
        dirs.append("ALTA" if a >= ANGULAR_LIMIAR_GRAUS else
                    "BAIXA" if a <= -ANGULAR_LIMIAR_GRAUS else "NEUTRA")
    positivas = sum(v == "ALTA" for v in dirs)
    negativas = sum(v == "BAIXA" for v in dirs)
    neutras = sum(v == "NEUTRA" for v in dirs)
    if positivas >= 2 and angulos[str(ANGULAR_JANELA_PADRAO)] > 0:
        direcao, estado = "CALL", "INCLINACAO_DE_ALTA"
    elif negativas >= 2 and angulos[str(ANGULAR_JANELA_PADRAO)] < 0:
        direcao, estado = "PUT", "INCLINACAO_DE_BAIXA"
    else:
        direcao, estado = "NEUTRA", "ANGULOS_MISTOS_OU_LATERAIS"
    alinhamento = ("ALINHADAS" if positivas == 3 or negativas == 3 else
                   "PARCIAL" if positivas >= 2 or negativas >= 2 else "SEM_ALINHAMENTO")
    return {
        "estado": estado, "direcao": direcao, "angulos": angulos,
        "inclinacoes_atr": inclinacoes, "direcoes_janelas": dict(zip(map(str, ANGULAR_JANELAS), dirs)),
        "alinhamento": alinhamento, "janela_principal": ANGULAR_JANELA_PADRAO,
        "limiar_graus": ANGULAR_LIMIAR_GRAUS, "atr": atr_val,
    }


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
    dmp = alta.where((alta > baixa) & (alta > 0), 0.0)
    dmn = baixa.where((baixa > alta) & (baixa > 0), 0.0)
    atr = calcular_atr(df, periodo).replace(0, np.nan)
    smp = dmp.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    smn = dmn.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    dip, dim = 100 * smp / atr, 100 * smn / atr
    soma = (dip + dim).replace(0, np.nan)
    dx = 100 * (dip - dim).abs() / soma
    adx = dx.ewm(
        alpha=1 / periodo, min_periods=periodo, adjust=False
    ).mean()
    return adx, dip, dim


def calcular_indicadores(df):
    df = df.copy()
    for p in (EMA_RAPIDA, EMA_MEDIA, EMA_TENDENCIA, EMA_LONGA):
        df[f"ema{p}"] = df["close"].ewm(span=p, adjust=False).mean()

    df["rsi"] = calcular_rsi(df["close"], PERIODO_RSI)
    df["atr"] = calcular_atr(df, PERIODO_ATR)
    df["adx"], df["di_positivo"], df["di_negativo"] = calcular_adx(
        df, PERIODO_ADX
    )
    df["momentum"] = df["close"] - df["close"].shift(PERIODO_MOMENTUM)

    # Fibonacci calculada a partir da amplitude máxima/mínima dos últimos 60 candles fechados.
    # O dataframe recebido nesta função já foi filtrado para excluir candles em formação.
    # A direção é definida pela ordem em que ocorreu o extremo mais antigo e o mais recente.
    janela_fib = JANELA_FIBONACCI
    n = len(df)
    tops = np.full(n, np.nan, dtype=float)
    fundos = np.full(n, np.nan, dtype=float)
    direcoes = np.full(n, "N/D", dtype=object)
    highs = df["max"].to_numpy(dtype=float)
    lows = df["min"].to_numpy(dtype=float)

    for i in range(n):
        inicio = max(0, i - janela_fib + 1)
        # Só calcula quando existem 60 candles fechados na janela.
        if i - inicio + 1 < janela_fib:
            continue
        janela_h = highs[inicio:i + 1]
        janela_l = lows[inicio:i + 1]
        idx_topo_local = int(np.argmax(janela_h))
        idx_fundo_local = int(np.argmin(janela_l))
        topo = float(janela_h[idx_topo_local])
        fundo = float(janela_l[idx_fundo_local])
        if not np.isfinite(topo) or not np.isfinite(fundo) or topo <= fundo:
            continue

        tops[i], fundos[i] = topo, fundo
        # Se o fundo ocorreu antes do topo, a pernada dominante da janela é de alta;
        # caso contrário, é de baixa. Em empate, conserva N/D para evitar direção arbitrária.
        if idx_fundo_local < idx_topo_local:
            direcoes[i] = "ALTA"
        elif idx_topo_local < idx_fundo_local:
            direcoes[i] = "BAIXA"

    topo_fib = pd.Series(tops, index=df.index)
    fundo_fib = pd.Series(fundos, index=df.index)
    amplitude_fib = topo_fib - fundo_fib
    direcao_fib_alta = pd.Series(direcoes == "ALTA", index=df.index)
    df["fib_topo"] = topo_fib
    df["fib_fundo"] = fundo_fib
    df["fib_amplitude"] = amplitude_fib
    df["fib_direcao_alta"] = direcao_fib_alta
    df["fib_382_alta"] = topo_fib - amplitude_fib * 0.382
    df["fib_500_alta"] = topo_fib - amplitude_fib * 0.500
    df["fib_618_alta"] = topo_fib - amplitude_fib * 0.618
    df["fib_786_alta"] = topo_fib - amplitude_fib * 0.786
    df["fib_918_alta"] = topo_fib - amplitude_fib * 0.918
    df["fib_382_baixa"] = fundo_fib + amplitude_fib * 0.382
    df["fib_500_baixa"] = fundo_fib + amplitude_fib * 0.500
    df["fib_618_baixa"] = fundo_fib + amplitude_fib * 0.618
    df["fib_786_baixa"] = fundo_fib + amplitude_fib * 0.786
    df["fib_918_baixa"] = fundo_fib + amplitude_fib * 0.918

    # Usa a direção determinada pela ordem dos extremos dentro da janela de 60 candles.
    usar_alta = direcao_fib_alta
    df["fib_382"] = np.where(usar_alta, df["fib_382_alta"], df["fib_382_baixa"])
    df["fib_500"] = np.where(usar_alta, df["fib_500_alta"], df["fib_500_baixa"])
    df["fib_618"] = np.where(usar_alta, df["fib_618_alta"], df["fib_618_baixa"])
    df["fib_786"] = np.where(usar_alta, df["fib_786_alta"], df["fib_786_baixa"])
    df["fib_918"] = np.where(usar_alta, df["fib_918_alta"], df["fib_918_baixa"])
    df["fib_direcao"] = pd.Series(direcoes, index=df.index)

    cols = [
        "ema3", "ema30", "ema60", "ema200", "rsi", "atr", "adx",
        "di_positivo", "di_negativo", "momentum"
    ]
    if df.iloc[-1][cols].isna().any():
        raise ValueError("Indicadores ainda sem dados validos.")
    return df


# ------------------ DETECCAO EXCLUSIVA 3S / 3C ------------------
def candle_info(row):
    o, c, h, l = map(
        float, (row["open"], row["close"], row["max"], row["min"])
    )
    amp = h - l
    if amp <= 0:
        return None

    corpo = abs(c - o)
    superior = h - max(o, c)
    inferior = min(o, c) - l

    return {
        "o": o, "c": c, "h": h, "l": l, "amp": amp, "corpo": corpo,
        "fracao_corpo": corpo / amp,
        "pavio_sup": superior / amp,
        "pavio_inf": inferior / amp,
        "alta": c > o, "baixa": c < o
    }


def detectar_tres_soldados(df):
    """Detecta tres candles de alta consecutivos, usando candles fechados."""
    r = {
        "detectado": False, "padrao": "NENHUM", "direcao": "NENHUMA",
        "motivos": [], "qualidade_estrutura": "N/D"
    }
    if df is None or len(df) < 3:
        r["motivos"] = ["Menos de 3 candles fechados."]
        return r

    xs = [candle_info(df.iloc[i]) for i in range(len(df) - 3, len(df))]
    if any(x is None for x in xs):
        r["motivos"] = ["Amplitude OHLC invalida."]
        return r

    a, b, c = xs
    todos_alta = all(x["alta"] for x in xs)
    tolerancia = (
        max(float(df.iloc[-1]["atr"]) * 0.08, 0.0)
        if "atr" in df.columns else 0.0
    )
    progressao = (
        b["c"] >= a["c"] - tolerancia
        and c["c"] >= b["c"] - tolerancia
        and c["c"] > a["c"]
    )
    aberturas_ok = (
        min(a["o"], a["c"]) - a["amp"] * SOBREPOSICAO_MAXIMA
        <= b["o"] <=
        max(a["o"], a["c"]) + a["amp"] * SOBREPOSICAO_MAXIMA
        and
        min(b["o"], b["c"]) - b["amp"] * SOBREPOSICAO_MAXIMA
        <= c["o"] <=
        max(b["o"], b["c"]) + b["amp"] * SOBREPOSICAO_MAXIMA
    )
    corpos_ok = all(
        CORPO_MINIMO_FRACAO <= x["fracao_corpo"] <= CORPO_MAXIMO_FRACAO
        for x in xs
    )
    pavios_ok = all(x["pavio_sup"] <= PAVIO_CONTRA_MAXIMO for x in xs)

    validos = (
        todos_alta and progressao and (aberturas_ok or corpos_ok)
        and corpos_ok and pavios_ok
    )
    motivos = [
        f"3 candles de alta: {'OK' if todos_alta else 'NAO'}",
        f"Fechamentos progressivos: {'OK' if progressao else 'NAO'}",
        f"Aberturas proximas aos corpos anteriores: "
        f"{'OK' if aberturas_ok else 'PARCIAL/NAO'}",
        f"Corpos entre {CORPO_MINIMO_FRACAO:.0%} e "
        f"{CORPO_MAXIMO_FRACAO:.0%}: {'OK' if corpos_ok else 'NAO'}",
        f"Pavio superior ate {PAVIO_CONTRA_MAXIMO:.0%}: "
        f"{'OK' if pavios_ok else 'NAO'}",
    ]

    if validos:
        qualidade = (
            "BOA" if aberturas_ok
            and all(x["fracao_corpo"] >= 0.40 for x in xs)
            else "MODERADA"
        )
        r.update(
            detectado=True, padrao="TRES SOLDADOS BRANCOS",
            direcao="CALL", motivos=motivos,
            qualidade_estrutura=qualidade
        )
    else:
        r["motivos"] = motivos
    return r


def detectar_tres_corvos(df):
    """Detecta tres candles de baixa consecutivos, usando candles fechados."""
    r = {
        "detectado": False, "padrao": "NENHUM", "direcao": "NENHUMA",
        "motivos": [], "qualidade_estrutura": "N/D"
    }
    if df is None or len(df) < 3:
        r["motivos"] = ["Menos de 3 candles fechados."]
        return r

    xs = [candle_info(df.iloc[i]) for i in range(len(df) - 3, len(df))]
    if any(x is None for x in xs):
        r["motivos"] = ["Amplitude OHLC invalida."]
        return r

    a, b, c = xs
    todos_baixa = all(x["baixa"] for x in xs)
    tolerancia = (
        max(float(df.iloc[-1]["atr"]) * 0.08, 0.0)
        if "atr" in df.columns else 0.0
    )
    progressao = (
        b["c"] <= a["c"] + tolerancia
        and c["c"] <= b["c"] + tolerancia
        and c["c"] < a["c"]
    )
    aberturas_ok = (
        min(a["o"], a["c"]) - a["amp"] * SOBREPOSICAO_MAXIMA
        <= b["o"] <=
        max(a["o"], a["c"]) + a["amp"] * SOBREPOSICAO_MAXIMA
        and
        min(b["o"], b["c"]) - b["amp"] * SOBREPOSICAO_MAXIMA
        <= c["o"] <=
        max(b["o"], b["c"]) + b["amp"] * SOBREPOSICAO_MAXIMA
    )
    corpos_ok = all(
        CORPO_MINIMO_FRACAO <= x["fracao_corpo"] <= CORPO_MAXIMO_FRACAO
        for x in xs
    )
    pavios_ok = all(x["pavio_inf"] <= PAVIO_CONTRA_MAXIMO for x in xs)

    validos = (
        todos_baixa and progressao and (aberturas_ok or corpos_ok)
        and corpos_ok and pavios_ok
    )
    motivos = [
        f"3 candles de baixa: {'OK' if todos_baixa else 'NAO'}",
        f"Fechamentos progressivos: {'OK' if progressao else 'NAO'}",
        f"Aberturas proximas aos corpos anteriores: "
        f"{'OK' if aberturas_ok else 'PARCIAL/NAO'}",
        f"Corpos entre {CORPO_MINIMO_FRACAO:.0%} e "
        f"{CORPO_MAXIMO_FRACAO:.0%}: {'OK' if corpos_ok else 'NAO'}",
        f"Pavio inferior ate {PAVIO_CONTRA_MAXIMO:.0%}: "
        f"{'OK' if pavios_ok else 'NAO'}",
    ]

    if validos:
        qualidade = (
            "BOA" if aberturas_ok
            and all(x["fracao_corpo"] >= 0.40 for x in xs)
            else "MODERADA"
        )
        r.update(
            detectado=True, padrao="TRES CORVOS NEGROS",
            direcao="PUT", motivos=motivos,
            qualidade_estrutura=qualidade
        )
    else:
        r["motivos"] = motivos
    return r


def detectar_padrao_combinado(df):
    """Detecta engolfo, rompimento de estrutura ou retração-retomada em candles fechados.

    Não substitui os detectores 3 Soldados/3 Corvos; serve como alternativa quando
    os padrões clássicos não aparecem. Não usa candle em formação nem preço sintético.
    """
    vazio = {"detectado": False, "padrao": "NENHUM", "direcao": "NENHUMA", "motivos": []}
    if df is None or len(df) < 22:
        return {**vazio, "motivos": ["Dados insuficientes para padrões combinados."]}
    a, b = df.iloc[-2], df.iloc[-1]
    vals = [float(a[k]) for k in ("open", "close", "min", "max")] + [float(b[k]) for k in ("open", "close", "min", "max")]
    if not all(np.isfinite(x) for x in vals):
        return {**vazio, "motivos": ["OHLC inválido no padrão combinado."]}
    ao, ac, al, ah, bo, bc, bl, bh = vals
    anteriores = df.iloc[-21:-1]
    topo = float(pd.to_numeric(anteriores["max"], errors="coerce").max())
    fundo = float(pd.to_numeric(anteriores["min"], errors="coerce").min())
    atr = float(b.get("atr", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return {**vazio, "motivos": ["ATR indisponível para validar o padrão combinado."]}

    # Rompimento confirmado do topo/fundo da janela anterior.
    if bc > bo and bc > topo and bc - bo >= 0.20 * atr:
        return {"detectado": True, "padrao": "ROMPIMENTO DE TOPO CONFIRMADO", "direcao": "CALL",
                "motivos": [f"Fechamento {bc:.5f} acima do topo anterior {topo:.5f}."] , "qualidade_estrutura": "MODERADA"}
    if bc < bo and bc < fundo and bo - bc >= 0.20 * atr:
        return {"detectado": True, "padrao": "ROMPIMENTO DE FUNDO CONFIRMADO", "direcao": "PUT",
                "motivos": [f"Fechamento {bc:.5f} abaixo do fundo anterior {fundo:.5f}."], "qualidade_estrutura": "MODERADA"}

    # Engolfo real do corpo anterior.
    if ac < ao and bc > bo and bo <= ac and bc >= ao:
        return {"detectado": True, "padrao": "ENGOLFO COMPRADOR", "direcao": "CALL",
                "motivos": ["Corpo comprador engolfa o corpo vendedor anterior."], "qualidade_estrutura": "MODERADA"}
    if ac > ao and bc < bo and bo >= ac and bc <= ao:
        return {"detectado": True, "padrao": "ENGOLFO VENDEDOR", "direcao": "PUT",
                "motivos": ["Corpo vendedor engolfa o corpo comprador anterior."], "qualidade_estrutura": "MODERADA"}

    # Retomada perto da EMA30 após candle contrário; requer fechamento de retomada.
    ema = float(b.get("ema30", np.nan))
    if np.isfinite(ema) and abs(bc - ema) <= 0.35 * atr:
        if ac < ao and bc > bo and bc > (bo + bc) / 2 and bc >= ema:
            return {"detectado": True, "padrao": "RETRACAO E RETOMADA DE ALTA", "direcao": "CALL",
                    "motivos": ["Candle vendedor seguido de retomada compradora próxima da EMA30."], "qualidade_estrutura": "MODERADA"}
        if ac > ao and bc < bo and bc < (bo + bc) / 2 and bc <= ema:
            return {"detectado": True, "padrao": "RETRACAO E RETOMADA DE BAIXA", "direcao": "PUT",
                    "motivos": ["Candle comprador seguido de retomada vendedora próxima da EMA30."], "qualidade_estrutura": "MODERADA"}
    return {**vazio, "motivos": ["Nenhum engolfo, rompimento ou retomada confirmado neste fechamento."]}



def _resultado_padrao(nome, direcao, motivos, qualidade="MODERADA"):
    return {"detectado": True, "padrao": nome, "direcao": direcao,
            "motivos": list(motivos), "qualidade_estrutura": qualidade}


def detectar_padroes_selecionaveis(df):
    """Avalia os 12 padrões selecionáveis usando exclusivamente OHLC fechado.

    Quando mais de um padrão surge no mesmo fechamento, ORDEM_PADROES é o
    desempate determinístico. Entre fechamentos, o scanner seleciona o primeiro
    padrão válido que aparecer, sem esperar por um padrão específico.
    """
    vazio = {"detectado": False, "padrao": "NENHUM", "direcao": "NENHUMA",
             "motivos": ["Nenhum padrão habilitado confirmado neste fechamento."],
             "qualidade_estrutura": "N/D"}
    if df is None or len(df) < 22:
        return {**vazio, "motivos": ["Dados insuficientes para avaliar os padrões selecionados."]}
    # Apenas as últimas velas FECHADAS do DataFrame validado pela API.
    a, b = df.iloc[-2], df.iloc[-1]
    try:
        ia, ib = candle_info(a), candle_info(b)
        ic = candle_info(df.iloc[-3])
        if any(x is None for x in (ia, ib, ic)):
            return {**vazio, "motivos": ["OHLC inválido; padrões não avaliados."]}
        atr = float(b.get("atr", np.nan))
        if not np.isfinite(atr) or atr <= 0:
            return {**vazio, "motivos": ["ATR inválido; padrões não avaliados."]}
    except Exception:
        return {**vazio, "motivos": ["Falha ao validar OHLC/ATR."]}

    candidatos = {}
    # Estrelas: vela 1 impulsiva, vela 2 de corpo pequeno e vela 3 oposta,
    # fechando além do ponto médio do corpo da primeira vela.
    if len(df) >= 3:
        x1, x2, x3 = [candle_info(df.iloc[i]) for i in range(len(df)-3, len(df))]
        if all(x is not None for x in (x1, x2, x3)):
            corpo_pequeno = x2["fracao_corpo"] <= 0.35 and x2["corpo"] <= max(x1["corpo"]*0.65, atr*0.35)
            meio_corpo1 = (x1["o"] + x1["c"]) / 2.0
            if x1["baixa"] and corpo_pequeno and x3["alta"] and x3["c"] > meio_corpo1 and x3["corpo"] >= 0.25*atr:
                candidatos["Estrela da Manhã"] = _resultado_padrao("ESTRELA DA MANHÃ", "CALL", ["Três velas fechadas: baixa, corpo central pequeno e recuperação acima do meio do corpo inicial."])
            if x1["alta"] and corpo_pequeno and x3["baixa"] and x3["c"] < meio_corpo1 and x3["corpo"] >= 0.25*atr:
                candidatos["Estrela da Noite"] = _resultado_padrao("ESTRELA DA NOITE", "PUT", ["Três velas fechadas: alta, corpo central pequeno e queda abaixo do meio do corpo inicial."])

    # Engolfos de corpo.
    if ia["baixa"] and ib["alta"] and ib["o"] <= ia["c"] and ib["c"] >= ia["o"]:
        candidatos["Engolfo de Alta"] = _resultado_padrao("ENGOLFO DE ALTA", "CALL", ["Corpo comprador engolfou o corpo vendedor anterior."])
    if ia["alta"] and ib["baixa"] and ib["o"] >= ia["c"] and ib["c"] <= ia["o"]:
        candidatos["Engolfo de Baixa"] = _resultado_padrao("ENGOLFO DE BAIXA", "PUT", ["Corpo vendedor engolfou o corpo comprador anterior."])

    soldados = detectar_tres_soldados(df)
    corvos = detectar_tres_corvos(df)
    if soldados.get("detectado"):
        candidatos["Três Soldados"] = _resultado_padrao("TRÊS SOLDADOS", "CALL", soldados.get("motivos", []), soldados.get("qualidade_estrutura", "MODERADA"))
    if corvos.get("detectado"):
        candidatos["Três Corvos"] = _resultado_padrao("TRÊS CORVOS", "PUT", corvos.get("motivos", []), corvos.get("qualidade_estrutura", "MODERADA"))

    # Harami: corpo atual dentro do corpo anterior e cor oposta.
    dentro = min(ia["o"], ia["c"]) <= min(ib["o"], ib["c"]) and max(ib["o"], ib["c"]) <= max(ia["o"], ia["c"])
    if ia["baixa"] and ib["alta"] and dentro and ib["corpo"] <= ia["corpo"]*0.70:
        candidatos["Harami de Alta"] = _resultado_padrao("HARAMI DE ALTA", "CALL", ["Corpo comprador pequeno contido no corpo vendedor anterior."])
    if ia["alta"] and ib["baixa"] and dentro and ib["corpo"] <= ia["corpo"]*0.70:
        candidatos["Harami de Baixa"] = _resultado_padrao("HARAMI DE BAIXA", "PUT", ["Corpo vendedor pequeno contido no corpo comprador anterior."])

    # Impulso: sequência direcional de pelo menos 2 velas e vela atual de corpo forte.
    if ic["alta"] and ib["alta"] and ib["fracao_corpo"] >= 0.60 and ib["corpo"] >= 0.80*atr and ib["c"] > ic["c"]:
        candidatos["Impulso de Alta"] = _resultado_padrao("IMPULSO DE ALTA", "CALL", ["Duas velas de alta consecutivas e vela atual com corpo >= 0,80 ATR."])
    if ic["baixa"] and ib["baixa"] and ib["fracao_corpo"] >= 0.60 and ib["corpo"] >= 0.80*atr and ib["c"] < ic["c"]:
        candidatos["Impulso de Baixa"] = _resultado_padrao("IMPULSO DE BAIXA", "PUT", ["Duas velas de baixa consecutivas e vela atual com corpo >= 0,80 ATR."])

    # Rompimento de máxima/mínima: fechamento além dos 20 candles anteriores.
    anteriores = df.iloc[-21:-1]
    topo = float(pd.to_numeric(anteriores["max"], errors="coerce").max())
    fundo = float(pd.to_numeric(anteriores["min"], errors="coerce").min())
    if np.isfinite(topo) and ib["alta"] and ib["c"] > topo and ib["corpo"] >= 0.20*atr:
        candidatos["Rompimento de máxima"] = _resultado_padrao("ROMPIMENTO DE MÁXIMA", "CALL", [f"Fechamento {ib['c']:.5f} acima da máxima dos 20 candles anteriores ({topo:.5f})."])
    if np.isfinite(fundo) and ib["baixa"] and ib["c"] < fundo and ib["corpo"] >= 0.20*atr:
        candidatos["Rompimento de mínima"] = _resultado_padrao("ROMPIMENTO DE MÍNIMA", "PUT", [f"Fechamento {ib['c']:.5f} abaixo da mínima dos 20 candles anteriores ({fundo:.5f})."])

    # Primeiro válido pela ordem selecionada; desempate pelo menu configurado.
    for nome in ORDEM_PADROES:
        if PADROES_HABILITADOS.get(nome, False) and nome in candidatos:
            selecionado = candidatos[nome]
            selecionado["motivos"].append("Selecionado pelo critério: primeiro padrão válido; confirmação no fechamento.")
            selecionado["padroes_detectados_mesmo_candle"] = [n for n in ORDEM_PADROES if n in candidatos]
            return selecionado
    return vazio


def avaliar_fibonacci(df, direcao="NENHUMA"):
    """Retorna contexto Fibonacci; nao confirma nem cria sinal isoladamente."""
    a = df.iloc[-1]
    campos = ["fib_topo", "fib_fundo", "fib_amplitude", "fib_382", "fib_500", "fib_618", "fib_786", "fib_918", "atr"]
    if any(pd.isna(a.get(k, np.nan)) for k in campos) or float(a["fib_amplitude"]) <= 0:
        return {
            "valido": False, "topo": np.nan, "fundo": np.nan, "amplitude": np.nan,
            "fib382": np.nan, "fib500": np.nan, "fib618": np.nan,
            "fib786": np.nan, "fib918": np.nan, "rompeu_786": False, "rompeu_918": False,
            "zona": False, "proximo": "N/D", "rejeicao": False,
            "distancia_atr": np.nan, "direcao": "N/D"
        }

    topo, fundo = float(a["fib_topo"]), float(a["fib_fundo"])
    f382, f500, f618 = float(a["fib_382"]), float(a["fib_500"]), float(a["fib_618"])
    f786, f918 = float(a["fib_786"]), float(a["fib_918"])
    atr = float(a["atr"])
    o, c, h, l = map(float, (a["open"], a["close"], a["max"], a["min"]))
    corpo = abs(c - o)
    pavio_sup = h - max(o, c)
    pavio_inf = min(o, c) - l

    # Zona de referencia Fibonacci entre 50% e 61.8%; tolerancia identifica proximidade.
    zona_min, zona_max = min(f500, f618), max(f500, f618)
    zona = h >= zona_min and l <= zona_max
    distancias = {
        "38.2%": abs(c - f382),
        "50.0%": abs(c - f500),
        "61.8%": abs(c - f618),
    }
    nivel_proximo = min(distancias, key=distancias.get)
    distancia_atr = distancias[nivel_proximo] / atr if atr > 0 else np.inf
    proximo = nivel_proximo if distancia_atr <= FIB_TOLERANCIA_ATR else "FORA DA ZONA"

    direcao_analise = direcao if direcao in ("CALL", "PUT") else str(a["fib_direcao"])
    rejeicao_alta = zona and c > o and c > f500 and pavio_inf > pavio_sup
    rejeicao_baixa = zona and c < o and c < f500 and pavio_sup > pavio_inf
    rejeicao = rejeicao_alta if direcao_analise == "CALL" else rejeicao_baixa if direcao_analise == "PUT" else (rejeicao_alta or rejeicao_baixa)

    # Em pernada de alta, rompimento profundo ocorre para baixo; em pernada de baixa, para cima.
    if str(a["fib_direcao"]) == "ALTA":
        rompeu_786 = c <= f786
        rompeu_918 = c <= f918
    else:
        rompeu_786 = c >= f786
        rompeu_918 = c >= f918

    return {
        "valido": True, "topo": topo, "fundo": fundo, "amplitude": float(a["fib_amplitude"]),
        "fib382": f382, "fib500": f500, "fib618": f618, "fib786": f786, "fib918": f918,
        "rompeu_786": bool(rompeu_786), "rompeu_918": bool(rompeu_918),
        "zona": bool(zona), "proximo": proximo, "rejeicao": bool(rejeicao),
        "distancia_atr": float(distancia_atr), "direcao": str(a["fib_direcao"])
    }



def avaliar_ondas_elliott(df):
    """Leitura heuristica de ondas Elliott usando apenas pivôs já confirmados.

    Retorna hipóteses, não uma contagem definitiva. Pivôs são confirmados
    com FIB_PIVOTO_LADO candles fechados à direita; não usa preços sintéticos.
    """
    lado = FIB_PIVOTO_LADO
    highs = df["max"].to_numpy(dtype=float)
    lows = df["min"].to_numpy(dtype=float)
    pivots = []
    fim = len(df) - lado  # não usa pivôs que ainda não foram confirmados
    for j in range(lado, fim):
        ini, fim_j = j - lado, j + lado + 1
        wh, wl = highs[ini:fim_j], lows[ini:fim_j]
        if highs[j] >= np.max(wh) and np.count_nonzero(wh == highs[j]) == 1:
            pivots.append((j, "H", float(highs[j])))
        if lows[j] <= np.min(wl) and np.count_nonzero(wl == lows[j]) == 1:
            pivots.append((j, "L", float(lows[j])))
    pivots.sort(key=lambda x: x[0])
    compact = []
    for pv in pivots:
        if compact and compact[-1][1] == pv[1]:
            old = compact[-1]
            more_extreme = pv[2] > old[2] if pv[1] == "H" else pv[2] < old[2]
            if more_extreme:
                compact[-1] = pv
        else:
            compact.append(pv)
    if len(compact) < 4:
        return {"estado": "AGUARDANDO PIVOS", "direcao": "N/D", "contagem": "N/D",
                "confianca": "BAIXA", "pivos": len(compact), "observacao": "Estrutura insuficiente"}

    # Últimos seis pivôs permitem testar uma sequência impulsiva aproximada.
    tail = compact[-6:]
    vals = [x[2] for x in tail]
    types = [x[1] for x in tail]
    result = {"estado": "CONTAGEM INDEFINIDA", "direcao": "LATERAL/INDEFINIDA",
              "contagem": "N/D", "confianca": "BAIXA", "pivos": len(compact),
              "observacao": "Pivôs sem estrutura Elliott suficientemente clara"}
    if len(tail) >= 6 and types == ["L", "H", "L", "H", "L", "H"]:
        # Cinco pontos alternados com máximas/mínimas ascendentes: possível impulso de alta.
        asc = vals[0] < vals[2] < vals[4] and vals[1] < vals[3] < vals[5]
        if asc:
            result.update(estado="POSSIVEL IMPULSO", direcao="ALTA", contagem="ONDAS 1-5 (hipotese)",
                          confianca="MODERADA", observacao="Máximas e mínimas ascendentes")
    elif len(tail) >= 6 and types == ["H", "L", "H", "L", "H", "L"]:
        desc = vals[0] > vals[2] > vals[4] and vals[1] > vals[3] > vals[5]
        if desc:
            result.update(estado="POSSIVEL IMPULSO", direcao="BAIXA", contagem="ONDAS 1-5 (hipotese)",
                          confianca="MODERADA", observacao="Máximas e mínimas descendentes")

    # Correção ABC: três movimentos alternados contra a direção da estrutura recente.
    if result["contagem"] == "N/D" and len(tail) >= 4:
        recent = tail[-4:]
        rv = [x[2] for x in recent]
        rt = [x[1] for x in recent]
        if rt == ["H", "L", "H", "L"] and rv[0] > rv[1] and rv[2] < rv[0] and rv[3] < rv[1]:
            result.update(estado="POSSIVEL CORRECAO", direcao="BAIXA/CORRETIVA", contagem="ABC (hipotese)",
                          confianca="BAIXA", observacao="Possível correção descendente; confirmar no preço")
        elif rt == ["L", "H", "L", "H"] and rv[0] < rv[1] and rv[2] > rv[0] and rv[3] > rv[1]:
            result.update(estado="POSSIVEL CORRECAO", direcao="ALTA/CORRETIVA", contagem="ABC (hipotese)",
                          confianca="BAIXA", observacao="Possível correção ascendente; confirmar no preço")
    return result


def avaliar_filtros(df, padrao):
    """Indicadores qualificam o padrao; nao criam sinais."""
    a = df.iloc[-1]
    direcao = padrao["direcao"]
    motivos, bloqueios = [], []
    atr = float(a.atr)
    esticamento = (
        abs(float(a.close) - float(a.ema30)) / atr if atr > 0 else np.inf
    )

    if direcao == "CALL":
        ema_ok = a.ema3 > a.ema30 and a.close > a.ema30
        di_ok = a.di_positivo > a.di_negativo
        momentum_ok = a.momentum > 0
        exaustao = a.rsi >= RSI_SOBRECOMPRA
        if a.rsi >= 70:
            motivos.append(
                "RSI elevado: observar possivel exaustao, sem bloqueio automatico"
            )
    else:
        ema_ok = a.ema3 < a.ema30 and a.close < a.ema30
        di_ok = a.di_negativo > a.di_positivo
        momentum_ok = a.momentum < 0
        exaustao = a.rsi <= RSI_SOBREVENDA
        if a.rsi <= 30:
            motivos.append(
                "RSI baixo: observar possivel exaustao, sem bloqueio automatico"
            )

    # Projecao angular entra na analise de direcao e na pontuacao contextual.
    # Usa somente candles fechados; nao cria sinal sem padrao 3S3C.
    angular = calcular_projecao_angular(df)
    direcao_angular = angular.get("direcao", "NEUTRA")
    angular_disponivel = bool(angular.get("angulos")) and direcao_angular in ("CALL", "PUT")
    angular_ok = angular_disponivel and direcao_angular == direcao
    angular_contraria = angular_disponivel and direcao_angular != direcao
    if angular_ok:
        motivos.append(
            f"Projecao angular ALINHADA com {direcao}: "
            f"5={angular['angulos'].get('5', 0.0):+.1f}°, "
            f"20={angular['angulos'].get('20', 0.0):+.1f}°, "
            f"60={angular['angulos'].get('60', 0.0):+.1f}°"
        )
    elif angular_contraria:
        motivos.append(
            f"ATENCAO: projecao angular {direcao_angular} DIVERGE do padrao {direcao}."
        )
    else:
        motivos.append("Projecao angular neutra/indisponivel; sem confirmacao direcional.")

    pontos = (
        int(bool(ema_ok)) + int(bool(di_ok)) + int(bool(momentum_ok))
        + int(float(a.adx) >= ADX_MINIMO)
        + int(30 < float(a.rsi) < 70)
        + int(bool(angular_ok))
    )

    motivos.append(
        f"ADX: {float(a.adx):.1f} "
        f"({'aceitavel' if a.adx >= ADX_MINIMO else 'fraco, apenas contexto'})"
    )
    motivos.append(
        "DI alinhado" if di_ok
        else "DI contra/sem confirmacao (nao bloqueia sozinho)"
    )
    motivos.append(
        "Momentum alinhado" if momentum_ok
        else "Momentum contra/sem confirmacao (nao bloqueia sozinho)"
    )
    motivos.append(
        "EMAs/preco alinhados" if ema_ok
        else "EMAs/preco sem alinhamento (nao bloqueia sozinho)"
    )
    motivos.append(f"Distancia EMA30: {esticamento:.2f} ATR")
    motivos.append(f"Pontuacao contextual: {pontos}/6 (inclui projecao angular)")

    if exaustao:
        motivos.append("ALERTA: RSI extremo; padrao pode estar exausto")
    if esticamento > MAX_ESTICAMENTO_ATR:
        motivos.append(
            "ALERTA: preco muito distante da EMA30; risco de retorno a media"
        )
    if esticamento > MAX_ESTICAMENTO_ATR * 1.5:
        bloqueios.append(
            "BLOQUEADO: distancia extrema da EMA30 (> 1.5x limite)."
        )
    if EXIGIR_CONTEXTO_EMA and not ema_ok:
        bloqueios.append("BLOQUEADO: contexto de EMAs nao confirma.")
    if EXIGIR_DI and not di_ok:
        bloqueios.append("BLOQUEADO: DI nao confirma a direcao.")
    if ANGULAR_EXIGIR_ALINHAMENTO and angular_disponivel and not angular_ok:
        bloqueios.append("BLOQUEADO: projecao angular nao confirma a direcao do padrao.")
    if ANGULAR_EXIGIR_ALINHAMENTO and not angular_disponivel:
        bloqueios.append("BLOQUEADO: projecao angular indisponivel para confirmar direcao.")

    aprovado = padrao["detectado"] and not bloqueios
    return {
        "aprovado": bool(aprovado), "ema_ok": bool(ema_ok),
        "di_ok": bool(di_ok), "momentum_ok": bool(momentum_ok),
        "angular_direcao": direcao_angular,
        "angular_ok": bool(angular_ok),
        "angular_disponivel": bool(angular_disponivel),
        "angular_angulos": angular.get("angulos", {}),
        "adx": float(a.adx), "rsi": float(a.rsi),
        "esticamento_atr": float(esticamento), "pontuacao": int(pontos),
        "motivos": motivos, "bloqueios": bloqueios
    }


# ---------------- PRIMEIRO ALVO PROVAVEL + VALIDACAO -----------------
def _pontuar_direcao(df, i, direcao, fibonacci=None, elliott=None):
    """Pontua contexto observável no candle i; não prevê com dados futuros."""
    a = df.iloc[i]
    anterior = df.iloc[max(0, i - 3):i + 1]
    if len(anterior) < 4:
        return 0, []
    pontos, motivos = 0, []
    alta = direcao == "CALL"
    ema_ok = (a.ema3 > a.ema30 > a.ema60 and a.close >= a.ema30) if alta else (a.ema3 < a.ema30 < a.ema60 and a.close <= a.ema30)
    di_ok = a.di_positivo > a.di_negativo if alta else a.di_negativo > a.di_positivo
    mom_ok = a.momentum > 0 if alta else a.momentum < 0
    rsi_ok = 45 <= float(a.rsi) <= 75 if alta else 25 <= float(a.rsi) <= 55
    adx_ok = float(a.adx) >= ADX_MINIMO
    delta = float(a.close) - float(anterior.iloc[0].close)
    velocidade_ok = delta > 0 if alta else delta < 0
    # Evita premiar preço muito esticado em relação à EMA30.
    atr = float(a.atr)
    esticamento = abs(float(a.close) - float(a.ema30)) / atr if atr > 0 else 999
    extensao_ok = esticamento <= MAX_ESTICAMENTO_ATR
    checks = [
        (ema_ok, "EMAs alinhadas"), (di_ok, "DI confirma direção"),
        (mom_ok, "Momentum alinhado"), (rsi_ok, "RSI sem extremo contrário"),
        (adx_ok, "ADX com força mínima"), (velocidade_ok, "movimento recente alinhado"),
        (extensao_ok, "extensão em ATR aceitável")
    ]
    for ok, motivo in checks:
        if bool(ok):
            pontos += 1
            motivos.append(motivo)
    if fibonacci and fibonacci.get("valido"):
        fib_dir = fibonacci.get("direcao", "N/D")
        if (alta and fib_dir == "ALTA") or ((not alta) and fib_dir == "BAIXA"):
            pontos += 1
            motivos.append("Fibonacci alinhada")
    if elliott:
        estado = str(elliott.get("estado", "")).upper()
        ell_dir = str(elliott.get("direcao", "")).upper()
        if "IMPULSO" in estado and ((alta and "ALTA" in ell_dir) or ((not alta) and "BAIXA" in ell_dir)):
            pontos += 1
            motivos.append("Elliott compatível (hipótese)")
    return pontos, motivos


def _obstaculo_e_alvo(df, i, direcao, fibonacci=None):
    """Calcula alvo ATR limitado por pivô/barreira conhecida até o candle i."""
    a = df.iloc[i]
    preco, atr = float(a.close), float(a.atr)
    if not np.isfinite(atr) or atr <= 0:
        return None
    inicio = max(0, i - 60)
    passado = df.iloc[inicio:i]  # estritamente anterior ao candle avaliado
    barreira = np.nan
    if len(passado) >= 7:
        hs = passado["max"].to_numpy(dtype=float)
        ls = passado["min"].to_numpy(dtype=float)
        pivots = []
        lado = 3
        for j in range(lado, len(passado) - lado):
            if hs[j] >= np.max(hs[j-lado:j+lado+1]) and np.count_nonzero(hs[j-lado:j+lado+1] == hs[j]) == 1:
                pivots.append(("H", float(hs[j])))
            if ls[j] <= np.min(ls[j-lado:j+lado+1]) and np.count_nonzero(ls[j-lado:j+lado+1] == ls[j]) == 1:
                pivots.append(("L", float(ls[j])))
        if direcao == "CALL":
            niveis = [v for t, v in pivots if t == "H" and v > preco]
            if niveis:
                barreira = min(niveis)
        else:
            niveis = [v for t, v in pivots if t == "L" and v < preco]
            if niveis:
                barreira = max(niveis)
    # Fibonacci atua como obstáculo potencial adicional, nunca como garantia.
    fib_rotulo = None
    if fibonacci and fibonacci.get("valido"):
        fib_keys = (("fib382", "38.2%"), ("fib500", "50.0%"),
                    ("fib618", "61.8%"), ("fib786", "78.6%"),
                    ("fib918", "91.8%"))
        fib_candidatos = []
        for key, rotulo in fib_keys:
            try:
                nivel = float(fibonacci.get(key, np.nan))
            except (TypeError, ValueError):
                continue
            if not np.isfinite(nivel):
                continue
            if direcao == "CALL" and nivel > preco:
                fib_candidatos.append((nivel, rotulo))
            elif direcao == "PUT" and nivel < preco:
                fib_candidatos.append((nivel, rotulo))
        if fib_candidatos:
            nivel_fib, rotulo_fib = (min(fib_candidatos, key=lambda x: x[0])
                                      if direcao == "CALL" else
                                      max(fib_candidatos, key=lambda x: x[0]))
            if not np.isfinite(barreira):
                barreira, fib_rotulo = nivel_fib, rotulo_fib
            else:
                dist_pivo = abs(barreira - preco)
                dist_fib = abs(nivel_fib - preco)
                if dist_fib < dist_pivo:
                    barreira, fib_rotulo = nivel_fib, rotulo_fib
    distancia_base = ALVO_ATR_BASE * atr
    if np.isfinite(barreira):
        espaco = (barreira - preco) if direcao == "CALL" else (preco - barreira)
        distancia_alvo = min(distancia_base, max(0.0, espaco - 0.10 * atr))
    else:
        espaco = np.nan
        distancia_alvo = distancia_base
    if distancia_alvo < ALVO_DISTANCIA_MIN_ATR * atr:
        return {
            "valido": False, "direcao": direcao, "preco": preco, "atr": atr,
            "alvo": np.nan, "inval": preco - atr if direcao == "CALL" else preco + atr,
            "barreira": barreira, "espaco_atr": espaco / atr if np.isfinite(espaco) else np.nan,
            "distancia_atr": distancia_alvo / atr, "motivo": "Obstáculo muito próximo"
        }
    alvo = preco + distancia_alvo if direcao == "CALL" else preco - distancia_alvo
    inval = preco - ALVO_INVALIDACAO_ATR * atr if direcao == "CALL" else preco + ALVO_INVALIDACAO_ATR * atr
    return {
        "valido": True, "direcao": direcao, "preco": preco, "atr": atr,
        "alvo": alvo, "inval": inval, "barreira": barreira,
        "espaco_atr": espaco / atr if np.isfinite(espaco) else np.nan,
        "distancia_atr": distancia_alvo / atr,
        "motivo": "Alvo limitado por ATR e obstáculo estrutural/Fibonacci conhecido",
        "barreira_tipo": (f"Fibonacci {fib_rotulo}" if fib_rotulo else
                          "Pivô estrutural" if np.isfinite(barreira) else "ATR")
    }


def _avaliar_resultado_futuro(df, i, candidato):
    """Resultado do alvo em candles posteriores; se alvo e invalidação no mesmo candle, marca ambíguo."""
    if not candidato or not candidato.get("valido"):
        return "SEM_ALVO"
    fim = min(len(df), i + 1 + ALVO_HORIZONTE_CANDLES)
    for j in range(i + 1, fim):
        c = df.iloc[j]
        if candidato["direcao"] == "CALL":
            hit = float(c["max"]) >= candidato["alvo"]
            stop = float(c["min"]) <= candidato["inval"]
        else:
            hit = float(c["min"]) <= candidato["alvo"]
            stop = float(c["max"]) >= candidato["inval"]
        if hit and stop:
            return "AMBIGUO"
        if hit:
            return "ALVO_ATINGIDO"
        if stop:
            return "INVALIDADO"
    if i + 1 + ALVO_HORIZONTE_CANDLES <= len(df):
        return "EXPIRADO"
    return "INCOMPLETO"


def _estatisticas_historicas(df):
    """Backtest walk-forward em candles fechados disponíveis; exclui casos incompletos/ambíguos."""
    n = len(df)
    inicio = max(EMA_LONGA + 5, n - ALVO_JANELA_HISTORICA)
    resultados = {"CALL": [], "PUT": []}
    for i in range(inicio, n - ALVO_HORIZONTE_CANDLES - 1):
        a = df.iloc[i]
        if not np.isfinite(float(a.atr)) or float(a.atr) <= 0:
            continue
        pcall, _ = _pontuar_direcao(df, i, "CALL")
        pput, _ = _pontuar_direcao(df, i, "PUT")
        if pcall >= 4 and pcall >= pput + 1:
            d = "CALL"
        elif pput >= 4 and pput >= pcall + 1:
            d = "PUT"
        else:
            continue
        cand = _obstaculo_e_alvo(df, i, d)
        resultado = _avaliar_resultado_futuro(df, i, cand)
        if resultado in ("ALVO_ATINGIDO", "INVALIDADO", "EXPIRADO"):
            resultados[d].append(resultado == "ALVO_ATINGIDO")
    stats = {}
    for d, vals in resultados.items():
        total = len(vals)
        stats[d] = {
            "amostras": total,
            "acertos": int(sum(vals)),
            "taxa": (100.0 * sum(vals) / total) if total else np.nan,
            "validada": total >= ALVO_AMOSTRA_MINIMA
        }
    return stats


def selecionar_primeiro_alvo(df, fibonacci=None, elliott=None):
    """Avalia CALL/PUT e retorna somente um alvo selecionado ou AGUARDAR."""
    a = df.iloc[-1]
    preco = float(a.close)
    candidatos = {}
    pontuacoes = {}
    motivos = {}
    for d in ("CALL", "PUT"):
        pts, why = _pontuar_direcao(df, len(df) - 1, d, fibonacci, elliott)
        pontuacoes[d], motivos[d] = pts, why
        candidatos[d] = _obstaculo_e_alvo(df, len(df) - 1, d, fibonacci=fibonacci)
    stats = _estatisticas_historicas(df)

    # Ângulo participa da seleção atual: voto por maioria das janelas 5/20/60.
    # Não se apresenta como probabilidade; só adiciona/remova uma confluência contextual.
    angular = calcular_projecao_angular(df)
    angulos = angular.get("angulos", {}) if isinstance(angular, dict) else {}
    votos_call = sum(1 for k in ("5", "20", "60")
                     if np.isfinite(angulos.get(k, np.nan)) and angulos.get(k, 0) >= ANGULAR_LIMIAR_GRAUS)
    votos_put = sum(1 for k in ("5", "20", "60")
                    if np.isfinite(angulos.get(k, np.nan)) and angulos.get(k, 0) <= -ANGULAR_LIMIAR_GRAUS)
    direcao_angular = "CALL" if votos_call >= 2 else "PUT" if votos_put >= 2 else "NEUTRA"
    for d in ("CALL", "PUT"):
        if direcao_angular == d:
            pontuacoes[d] += 1
            motivos[d].append(f"Projeção angular alinhada ({votos_call if d == 'CALL' else votos_put}/3 janelas)")
        elif direcao_angular in ("CALL", "PUT"):
            pontuacoes[d] = max(0, pontuacoes[d] - 1)
            motivos[d].append(f"Projeção angular divergente ({direcao_angular})")
        else:
            motivos[d].append("Projeção angular sem maioria direcional")

    # MODO COMPRA E VENDA: cada direção é elegível apenas se atingir o placar mínimo
    # e possuir primeiro alvo estrutural válido.
    elegiveis = [d for d in ("CALL", "PUT")
                 if pontuacoes[d] >= 4 and candidatos[d] and candidatos[d].get("valido")]
    if not elegiveis:
        return {"estado": "AGUARDAR", "direcao": "NENHUMA", "preco_referencia": preco,
                "alvo": np.nan, "distancia": np.nan, "distancia_atr": np.nan,
                "horizonte": ALVO_HORIZONTE_CANDLES, "barreira": np.nan,
                "inval": np.nan, "probabilidade": np.nan, "validacao": "AINDA NÃO VALIDADA",
                "amostras": 0, "motivos": ["Nenhuma direção tem confluência e espaço estrutural suficientes."], "stats": stats,
                "pontuacoes": pontuacoes, "direcao_angular": direcao_angular,
                "votos_angular_call": votos_call, "votos_angular_put": votos_put}

    # Se ambos passarem, a taxa histórica só desempata quando houver amostra mínima.
    if len(elegiveis) == 2:
        diff = pontuacoes["CALL"] - pontuacoes["PUT"]
        cvalid, pvalid = stats["CALL"]["validada"], stats["PUT"]["validada"]
        if cvalid and pvalid and abs(stats["CALL"]["taxa"] - stats["PUT"]["taxa"]) >= 2:
            direcao = "CALL" if stats["CALL"]["taxa"] > stats["PUT"]["taxa"] else "PUT"
        elif abs(diff) >= 2:
            direcao = "CALL" if diff > 0 else "PUT"
        else:
            return {"estado": "AGUARDAR", "direcao": "NENHUMA", "preco_referencia": preco,
                    "alvo": np.nan, "distancia": np.nan, "distancia_atr": np.nan,
                    "horizonte": ALVO_HORIZONTE_CANDLES, "barreira": np.nan,
                    "inval": np.nan, "probabilidade": np.nan,
                    "validacao": "SEM DESEMPATE CONFIÁVEL", "amostras": 0,
                    "motivos": ["CALL e PUT estão próximos; não há vantagem suficiente para escolher um."], "stats": stats,
                    "pontuacoes": pontuacoes, "direcao_angular": direcao_angular,
                    "votos_angular_call": votos_call, "votos_angular_put": votos_put}
    else:
        direcao = elegiveis[0]

    cand = candidatos[direcao]
    st = stats[direcao]
    validacao = "VALIDADA NO HISTÓRICO" if st["validada"] else "AINDA NÃO VALIDADA"
    prob = st["taxa"] if st["validada"] else np.nan
    barreira = cand["barreira"]
    if np.isfinite(barreira):
        obstaculo = f"{barreira:.5f} ({cand.get('barreira_tipo', 'estrutura')})"
    else:
        obstaculo = "Nenhum pivô/Fibonacci próximo"
    return {
        "estado": "ALVO SELECIONADO", "direcao": direcao,
        "preco_referencia": cand["preco"], "alvo": cand["alvo"],
        "distancia": abs(cand["alvo"] - cand["preco"]),
        "distancia_atr": cand["distancia_atr"],
        "horizonte": ALVO_HORIZONTE_CANDLES, "barreira": barreira,
        "obstaculo_texto": obstaculo, "inval": cand["inval"],
        "probabilidade": prob, "validacao": validacao,
        "amostras": st["amostras"], "acertos": st["acertos"],
        "pontuacao": pontuacoes[direcao], "motivos": motivos[direcao],
        "stats": stats, "resultado_metodo": cand["motivo"],
        "direcao_angular": direcao_angular,
        "votos_angular_call": votos_call, "votos_angular_put": votos_put,
        "pontuacoes": pontuacoes,
        "barreira_tipo": cand.get("barreira_tipo", "N/D")
    }


def registrar_validacao_alvo(timestamp, alvo):
    """Registra apenas a seleção atual; a taxa é recalculada walk-forward em cada ciclo."""
    reg = {
        "horario_registro": datetime.now().isoformat(timespec="seconds"),
        "ativo": ATIVO, "timeframe": TIMEFRAME_LABEL, "timestamp_candle": int(timestamp),
        "estado": alvo.get("estado"), "direcao": alvo.get("direcao"),
        "preco_referencia": alvo.get("preco_referencia"), "alvo": alvo.get("alvo"),
        "distancia": alvo.get("distancia"), "distancia_atr": alvo.get("distancia_atr"),
        "horizonte_candles": alvo.get("horizonte"), "barreira": alvo.get("barreira"),
        "inval": alvo.get("inval"), "validacao": alvo.get("validacao"),
        "probabilidade_historica_pct": alvo.get("probabilidade"),
        "amostras_historicas": alvo.get("amostras"),
        "pontuacao_contexto": alvo.get("pontuacao"),
        "motivos": " | ".join(alvo.get("motivos", [])),
        "nota": "Registro informativo; sem ordens automáticas."
    }
    existe = os.path.exists(ARQUIVO_VALIDACAO_ALVOS)
    pd.DataFrame([reg]).to_csv(ARQUIVO_VALIDACAO_ALVOS, mode="a", header=not existe, index=False)


# ------------------------- REGISTRO CSV -------------------------
def salvar_csv(df, padrao, filtros, status, fibonacci=None, elliott=None, primeiro_alvo=None):
    a = df.iloc[-1]
    fibonacci = fibonacci or {}
    elliott = elliott or {}
    primeiro_alvo = primeiro_alvo or {}
    reg = {
        "ativo": ATIVO,
        "timeframe": TIMEFRAME_LABEL,
        "horario_local": datetime.now().isoformat(timespec="seconds"),
        "timestamp_candle_fechado": int(a["to"]),
        "open": float(a.open), "high": float(a["max"]),
        "low": float(a["min"]), "close": float(a.close),
        "padrao": padrao["padrao"], "direcao": padrao["direcao"],
        "padrao_detectado": bool(padrao["detectado"]),
        "sinal_aprovado": bool(filtros["aprovado"]),
        "status": status,
        "ema3": float(a.ema3), "ema30": float(a.ema30),
        "ema60": float(a.ema60), "ema200": float(a.ema200),
        "rsi": float(a.rsi), "atr": float(a.atr), "adx": float(a.adx),
        "di_positivo": float(a.di_positivo),
        "di_negativo": float(a.di_negativo),
        "momentum": float(a.momentum),
        "fib_topo": float(a.fib_topo) if pd.notna(a.fib_topo) else np.nan,
        "fib_fundo": float(a.fib_fundo) if pd.notna(a.fib_fundo) else np.nan,
        "fib_382": float(a.fib_382) if pd.notna(a.fib_382) else np.nan,
        "fib_500": float(a.fib_500) if pd.notna(a.fib_500) else np.nan,
        "fib_618": float(a.fib_618) if pd.notna(a.fib_618) else np.nan,
        "fib_786": float(a.fib_786) if pd.notna(a.fib_786) else np.nan,
        "fib_918": float(a.fib_918) if pd.notna(a.fib_918) else np.nan,
        "fib_rompeu_786": bool(fibonacci.get("rompeu_786", False)),
        "fib_rompeu_918": bool(fibonacci.get("rompeu_918", False)),
        "fib_direcao": str(a.fib_direcao),
        "fib_zona_50_618": bool(fibonacci.get("zona", False)),
        "fib_nivel_proximo": fibonacci.get("proximo", "N/D"),
        "fib_rejeicao": bool(fibonacci.get("rejeicao", False)),
        "fib_distancia_atr": fibonacci.get("distancia_atr", np.nan),
        "elliott_estado": elliott.get("estado", "N/D"),
        "elliott_direcao": elliott.get("direcao", "N/D"),
        "elliott_contagem": elliott.get("contagem", "N/D"),
        "elliott_confianca": elliott.get("confianca", "N/D"),
        "elliott_pivos": elliott.get("pivos", 0),
        "elliott_observacao": elliott.get("observacao", "N/D"),
        "esticamento_atr": filtros["esticamento_atr"],
        "pontuacao_contexto": filtros.get("pontuacao", 0),
        "angular_direcao": filtros.get("angular_direcao", "N/D"),
        "angular_alinhada": filtros.get("angular_ok", False),
        "angular_angulo_5": filtros.get("angular_angulos", {}).get("5", np.nan),
        "angular_angulo_20": filtros.get("angular_angulos", {}).get("20", np.nan),
        "angular_angulo_60": filtros.get("angular_angulos", {}).get("60", np.nan),
        "qualidade_estrutura": padrao.get("qualidade_estrutura", "N/D"),
        "motivos_padrao": " | ".join(padrao["motivos"]),
        "motivos_filtros": " | ".join(filtros["motivos"]),
        "bloqueios": " | ".join(filtros["bloqueios"]),
        "primeiro_alvo_estado": primeiro_alvo.get("estado", "N/D"),
        "primeiro_alvo_direcao": primeiro_alvo.get("direcao", "N/D"),
        "primeiro_alvo_preco": primeiro_alvo.get("alvo", np.nan),
        "primeiro_alvo_distancia": primeiro_alvo.get("distancia", np.nan),
        "primeiro_alvo_distancia_atr": primeiro_alvo.get("distancia_atr", np.nan),
        "primeiro_alvo_horizonte_candles": primeiro_alvo.get("horizonte", ALVO_HORIZONTE_CANDLES),
        "primeiro_alvo_barreira": primeiro_alvo.get("barreira", np.nan),
        "primeiro_alvo_inval": primeiro_alvo.get("inval", np.nan),
        "primeiro_alvo_validacao": primeiro_alvo.get("validacao", "AINDA NÃO VALIDADA"),
        "primeiro_alvo_probabilidade_pct": primeiro_alvo.get("probabilidade", np.nan),
        "primeiro_alvo_amostras": primeiro_alvo.get("amostras", 0),
        "primeiro_alvo_motivos": " | ".join(primeiro_alvo.get("motivos", [])),
        "observacao": "Sinal técnico informativo; não é garantia nem ordem."
    }

    for arquivo in (ARQUIVO_HISTORICO, ARQUIVO_PADROES):
        existe = os.path.exists(arquivo)
        pd.DataFrame([reg]).to_csv(
            arquivo, mode="a", header=not existe, index=False
        )


# ---------------- CONTEXTO MULTITIMEFRAME SWING ----------------
def obter_contexto_superior(api, intervalo, quantidade, nome):
    """Lê candles reais fechados do timeframe superior; não cria nem preenche candles."""
    agora = time.time()
    dados = api.get_candles(ATIVO, intervalo, quantidade, agora)
    if not dados:
        raise ValueError(f"API sem candles {nome}.")
    df = validar_candles(pd.DataFrame(dados), minimo=30)
    df = df[df["to"] < agora].copy().sort_values("from").drop_duplicates("from")
    if len(df) < 30:
        raise ValueError(f"Candles fechados insuficientes em {nome}: {len(df)}")
    close = pd.to_numeric(df["close"], errors="coerce")
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ultimo = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    if ultimo > e20 and e20 > e50:
        direcao = "ALTA"
    elif ultimo < e20 and e20 < e50:
        direcao = "BAIXA"
    else:
        direcao = "NEUTRA/MISTA"
    return {"timeframe": nome, "direcao": direcao, "close": ultimo,
            "ema20": e20, "ema50": e50, "timestamp": int(df.iloc[-1]["to"]),
            "candles": len(df)}

def obter_contexto_mensal(api):
    """Monta contexto MN1 por mês-calendário a partir de candles D1 reais fechados.

    Não usa timeframe fixo de 30 dias, pois meses têm comprimentos diferentes.
    Cada mês fechado usa open do primeiro candle D1, máximo/mínimo observados e
    close do último candle D1 do mês. O mês corrente é sempre excluído.
    """
    agora = time.time()
    # Até 1200 candles diários (~3,3 anos) para construir contexto mensal suficiente.
    dados = api.get_candles(ATIVO, INTERVALO_MN1_FONTE, 1200, agora)
    if not dados:
        raise ValueError("API sem candles D1 para calcular contexto MN1.")
    df = validar_candles(pd.DataFrame(dados), minimo=120)
    df = df[df["to"] < agora].copy().sort_values("from").drop_duplicates("from")
    if len(df) < 120:
        raise ValueError(f"Candles D1 fechados insuficientes para MN1: {len(df)}")
    dt = pd.to_datetime(df["from"], unit="s", utc=True)
    df["_mes"] = dt.dt.strftime("%Y-%m")
    mes_corrente = pd.Timestamp.now(tz="UTC").strftime("%Y-%m")
    df = df[df["_mes"] < mes_corrente].copy()
    mensal = df.groupby("_mes", sort=True).agg(
        open=("open", "first"), close=("close", "last"),
        min=("min", "min"), max=("max", "max"),
        **{"from": ("from", "first"), "to": ("to", "last")}
    ).reset_index(drop=True)
    mensal = validar_candles(mensal, minimo=MESES_MINIMOS_CONTEXTO)
    close = pd.to_numeric(mensal["close"], errors="coerce")
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ultimo, e20, e50 = float(close.iloc[-1]), float(ema20.iloc[-1]), float(ema50.iloc[-1])
    if ultimo > e20 and e20 > e50:
        direcao = "ALTA"
    elif ultimo < e20 and e20 < e50:
        direcao = "BAIXA"
    else:
        direcao = "NEUTRA/MISTA"
    return {"timeframe": "MN1", "direcao": direcao, "close": ultimo,
            "ema20": e20, "ema50": e50, "timestamp": int(mensal.iloc[-1]["to"]),
            "candles": len(mensal), "metodo": "D1 REAL AGREGADO POR MES-CALENDARIO"}


def atualizar_contexto_swing(api):
    """Atualiza contexto MN1/D1/W1 usando apenas candles superiores fechados."""
    global CONTEXTO_SWING, ULTIMA_ATUALIZACAO_CONTEXTO
    agora = time.time()
    if CONTEXTO_SWING and agora - ULTIMA_ATUALIZACAO_CONTEXTO < 900:
        return CONTEXTO_SWING
    novo = {}
    erros = []
    try:
        novo["MN1"] = obter_contexto_mensal(api)
    except Exception as exc:
        erros.append(f"MN1: {exc.__class__.__name__}: {exc}")
    for nome, intervalo, qtd in (("D1", INTERVALO_D1, 120), ("W1", INTERVALO_W1, 80)):
        try:
            novo[nome] = obter_contexto_superior(api, intervalo, qtd, nome)
        except Exception as exc:
            erros.append(f"{nome}: {exc.__class__.__name__}")
    novo["erro"] = "; ".join(erros) if erros else ""
    if any(novo.get(tf) for tf in ("MN1", "D1", "W1")):
        CONTEXTO_SWING = novo
        ULTIMA_ATUALIZACAO_CONTEXTO = agora
    return CONTEXTO_SWING

def resumo_confluencia_swing(contexto, direcao):
    """MN1/D1/W1 são contexto; o gatilho continua sendo candle H4 fechado."""
    if direcao not in ("CALL", "PUT"):
        return "SEM DIRECAO H4"
    alvo = "ALTA" if direcao == "CALL" else "BAIXA"
    dirs = [contexto.get(tf, {}).get("direcao") for tf in ("MN1", "W1", "D1")]
    alinhados = sum(d == alvo for d in dirs)
    opostos = sum(d in ("ALTA", "BAIXA") and d != alvo for d in dirs)
    if alinhados == 3:
        return "ALINHADO MN1+W1+D1"
    if opostos:
        return "CONFLITO COM CONTEXTO SUPERIOR"
    return "CONFLUENCIA PARCIAL/NEUTRA"

# ------------------------- PAINEL -------------------------------
def analisar_autorizacao_pernada(df, pernada):
    """Classifica oportunidades de entrada em pernadas, sem enviar ordens.

    A autorização usa exclusivamente candles H4 fechados. A cotação viva não
    confirma rompimentos nem muda o estado de autorização.
    """
    vazio = {
        "direcao": "NENHUMA", "status": "AGUARDAR", "tipo": "SEM LEITURA",
        "motivo": "Dados insuficientes para validar a entrada.",
        "estrutura": "INDETERMINADA", "retomada": False,
        "esticada": False, "pullback": False,
    }
    if df is None or len(df) < 8 or not isinstance(pernada, dict):
        return vazio.copy()
    try:
        d = df.tail(12).copy().reset_index(drop=True)
        for c in ("close", "max", "min"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        if d[["close", "max", "min"]].tail(6).isna().any().any():
            return vazio.copy()
        direcao = "ALTA" if pernada.get("pivo_tipo") == "FUNDO" else "BAIXA" if pernada.get("pivo_tipo") == "TOPO" else pernada.get("direcao", "NENHUMA")
        if direcao not in ("ALTA", "BAIXA"):
            return vazio.copy()
        close = d["close"].to_numpy(float)
        highs = d["max"].to_numpy(float)
        lows = d["min"].to_numpy(float)
        a = d.iloc[-1]
        atr = float(a.get("atr", np.nan))
        pivot = float(pernada.get("pivo_preco", np.nan))
        bars = int(pernada.get("barras_pernada", 0) or 0)
        progress = float(pernada.get("progresso_pct", np.nan))
        dist_atr = float(pernada.get("distancia_atr", np.nan))
        if not np.isfinite(pivot) or not np.isfinite(close[-1]):
            return vazio.copy()

        # A estrutura de origem não pode ter sido violada no sentido contrário.
        invalidada = (direcao == "ALTA" and close[-1] < pivot) or (direcao == "BAIXA" and close[-1] > pivot)
        if invalidada:
            return {**vazio, "direcao": direcao, "status": "BLOQUEADA", "tipo": "ESTRUTURA INVALIDADA",
                    "motivo": "O fechamento atravessou o pivô de origem; não autorizar continuação nessa direção.",
                    "estrutura": "INVALIDADA"}

        # Confirmação de retomada: fechamento rompe a máxima/mínima das 3 barras
        # anteriores, sem usar a barra atual no cálculo do nível de rompimento.
        if direcao == "ALTA":
            nivel = float(np.max(highs[-4:-1]))
            retomada = close[-1] > nivel
            candle_direcional = close[-1] > close[-2]
            opostos = sum(1 for i in range(max(1, len(close)-5), len(close)-1) if close[i] < close[i-1])
        else:
            nivel = float(np.min(lows[-4:-1]))
            retomada = close[-1] < nivel
            candle_direcional = close[-1] < close[-2]
            opostos = sum(1 for i in range(max(1, len(close)-5), len(close)-1) if close[i] > close[i-1])
        pullback = opostos >= 1
        esticada = ((np.isfinite(progress) and progress >= 85.0) or
                    (np.isfinite(dist_atr) and dist_atr >= 1.8))
        espaco_ok = not (np.isfinite(atr) and atr > 0 and np.isfinite(dist_atr) and dist_atr >= 3.2)

        if esticada:
            if retomada and pullback and espaco_ok:
                return {"direcao": direcao, "status": "CANDIDATA VALIDADA", "tipo": "CONTINUACAO APOS EXAUSTAO",
                        "motivo": "Pernada estendida, estrutura preservada, recuo recente e retomada confirmada por candle fechado.",
                        "estrutura": "PRESERVADA", "retomada": True, "esticada": True, "pullback": True}
            return {"direcao": direcao, "status": "BLOQUEADA", "tipo": "PERNADA ESTENDIDA",
                    "motivo": "Não perseguir o preço: aguardar recuo e fechamento confirmando retomada; extensão elevada aumenta o risco de entrada tardia.",
                    "estrutura": "PRESERVADA", "retomada": bool(retomada), "esticada": True, "pullback": bool(pullback)}

        if bars <= 4 and retomada and candle_direcional and espaco_ok:
            return {"direcao": direcao, "status": "CANDIDATA VALIDADA", "tipo": "INICIO DA PERNADA",
                    "motivo": "Pivô confirmado, fechamento rompeu a faixa curta na direção da pernada e a extensão ainda não está elevada.",
                    "estrutura": "PRESERVADA", "retomada": True, "esticada": False, "pullback": bool(pullback)}
        if retomada and candle_direcional and espaco_ok:
            return {"direcao": direcao, "status": "CANDIDATA VALIDADA", "tipo": "CONTINUACAO CONFIRMADA",
                    "motivo": "Fechamento rompeu o extremo das três barras anteriores na direção da pernada, com estrutura preservada.",
                    "estrutura": "PRESERVADA", "retomada": True, "esticada": False, "pullback": bool(pullback)}
        return {"direcao": direcao, "status": "AGUARDAR", "tipo": "SEM RETOMADA CONFIRMADA",
                "motivo": "A direção estrutural está identificada, mas falta fechamento confirmando avanço; não antecipar a entrada.",
                "estrutura": "PRESERVADA", "retomada": bool(retomada), "esticada": False, "pullback": bool(pullback)}
    except Exception as exc:
        return {**vazio, "motivo": f"Falha na análise de entrada da pernada: {exc.__class__.__name__}"}


def emitir_painel(df, soldados, corvos, padrao, filtros, fibonacci=None, elliott=None, primeiro_alvo=None, radar_estrutura=None, estatisticas_estrutura=None):
    """Painel reduzido: somente estrutura de topos/fundos orienta a análise."""
    a = df.iloc[-1]
    os.system("clear")
    print(cor("=" * 68, AZUL))
    print(cor("QMS SWING TRADER H4 | CONTEXTO MN1/D1/W1".center(68), AZUL))
    print(cor("=" * 68, AZUL))
    print(f"Ativo: {ATIVO} | Timeframe: H4 | Contexto: MN1/D1/W1 | Conta: {CONTA} | Somente leitura")
    print("Candle fechado: " + datetime.fromtimestamp(int(a["to"])).strftime("%Y-%m-%d %H:%M:%S"))
    print("Método: extremos da janela + rejeição do candle fechado")
    print("Gatilho: H4 fechado | Contexto: MN1, D1 e W1 fechados | Swing: semanas a meses")
    print("Indicadores/Fibonacci/Elliott são apoio informativo; não garantem resultado.")
    print(cor("\n[CONTEXTO MULTITIMEFRAME SWING]", AZUL))
    for tf in ("MN1", "W1", "D1"):
        ctx = CONTEXTO_SWING.get(tf, {})
        if ctx:
            hora_ctx = datetime.fromtimestamp(int(ctx.get("timestamp", 0))).strftime("%Y-%m-%d")
            print(f"{tf}: {ctx.get('direcao','N/D')} | fechamento {fmt(ctx.get('close'))} | EMA20 {fmt(ctx.get('ema20'))} | EMA50 {fmt(ctx.get('ema50'))} | candle fechado {hora_ctx}" + (f" | método {ctx.get('metodo')}" if ctx.get("metodo") else ""))
        else:
            print(f"{tf}: CONTEXTO INDISPONIVEL — não presumir alinhamento")
    if CONTEXTO_SWING.get("erro"):
        print("Aviso contexto: " + str(CONTEXTO_SWING.get("erro")))

    topo = padrao.get("referencia_topo", np.nan)
    fundo = padrao.get("referencia_fundo", np.nan)
    print("\n" + cor("[ESTRUTURA ATUAL]", AZUL))
    print(f"Topo da janela: {fmt(topo)}")
    print(f"Fundo da janela: {fmt(fundo)}")
    print(f"Preço de fechamento: {fmt(float(a['close']))}")
    pernada = ULTIMA_PERNADA_DINAMICA or analisar_pernada_dinamica(df, float(a["close"]))
    print(cor("\n[ANALISE DINAMICA DA PERNADA]", AZUL))
    print(f"Direção da pernada: {pernada.get('direcao', 'N/D')} | Estado: {pernada.get('estado', 'N/D')}")
    print(f"Pivô de origem: {pernada.get('pivo_tipo', 'N/D')} em {fmt(pernada.get('pivo_preco', np.nan))} | Barras desde pivô: {pernada.get('barras_pernada', 0)}")
    print(f"Amplitude atual: {fmt(pernada.get('amplitude', np.nan))} | Progresso vs pernada anterior: {fmt(pernada.get('progresso_pct', np.nan))}% | ATR: {fmt(pernada.get('distancia_atr', np.nan))}")
    print("Leitura: " + str(pernada.get("mensagem", "N/D")))
    autorizacao_pernada = analisar_autorizacao_pernada(df, pernada)
    print(cor("\n[AUTORIZACAO DE ENTRADA NA PERNADA]", AZUL))
    cor_status = VERDE if autorizacao_pernada.get("status") == "CANDIDATA VALIDADA" else AMARELO if autorizacao_pernada.get("status") == "AGUARDAR" else VERMELHO
    print(cor(f"Direcao: {autorizacao_pernada.get('direcao', 'NENHUMA')} | Tipo: {autorizacao_pernada.get('tipo', 'N/D')}", cor_status))
    print(cor(f"ENTRADA: {autorizacao_pernada.get('status', 'AGUARDAR')}", cor_status))
    print("Estrutura: " + str(autorizacao_pernada.get("estrutura", "N/D")) +
          " | Retomada confirmada: " + ("SIM" if autorizacao_pernada.get("retomada") else "NAO") +
          " | Pernada estendida: " + ("SIM" if autorizacao_pernada.get("esticada") else "NAO"))
    print("Motivo: " + str(autorizacao_pernada.get("motivo", "N/D")))
    print(f"Estado: {padrao.get('estado_estrutura', 'N/D')}")
    print(f"Leitura: {padrao.get('padrao', 'AGUARDANDO TOPO/FUNDO')}")
    for motivo in padrao.get("motivos", []):
        print(" - " + str(motivo))

    if padrao.get("detectado") and padrao.get("direcao") in ("CALL", "PUT"):
        lado = padrao["direcao"]
        codigo = VERDE if lado == "CALL" else VERMELHO
        nome = "CALL — REJEIÇÃO DE FUNDO" if lado == "CALL" else "PUT — REJEIÇÃO DE TOPO"
        print("\n" + cor("SINAL ESTRUTURAL: " + nome, codigo))
        print("Confirmação baseada apenas no candle fechado e na localização do extremo.")
    else:
        print("\n" + cor("AGUARDAR — SEM REJEIÇÃO VÁLIDA EM TOPO/FUNDO", AMARELO))

    confluencia = filtros.get("confluencia_total", {})
    if confluencia:
        print("\nAutorização por topo/fundo: " + ("LIBERADA" if confluencia.get("liberado") else "BLOQUEADA"))
    print("Nenhuma ordem enviada | Sem ordens automáticas | Sem Martingale")
    print(cor("=" * 68, AZUL))

def registrar_rompimento_lateral(padrao):
    """Persiste rompimentos confirmados da faixa lateral para validação posterior."""
    if not padrao or not padrao.get("detectado"):
        return
    arquivo = ARQUIVO_ROMPIMENTOS_LATERAL
    row = {"ativo": ATIVO, "timeframe": TIMEFRAME_LABEL, "nome": padrao.get("nome"),
           "direcao": padrao.get("direcao"), "estado": padrao.get("estado"),
           "timestamp_sinal": padrao.get("timestamp_sinal"),
           "horario_sinal": datetime.fromtimestamp(int(padrao.get("timestamp_sinal", time.time()))).isoformat(timespec="seconds"),
           "preco_sinal": padrao.get("preco_sinal"), "limite_superior": padrao.get("limite_superior"),
           "limite_inferior": padrao.get("limite_inferior"), "atr": padrao.get("atr"),
           "buffer": padrao.get("buffer"), "observacao": padrao.get("observacao")}
    if os.path.exists(arquivo):
        try:
            old = pd.read_csv(arquivo)
            duplicado = False
            if {"timestamp_sinal", "ativo", "nome"}.issubset(old.columns):
                duplicado = bool(((old["ativo"].astype(str) == ATIVO) &
                                  (old["nome"].astype(str) == str(row["nome"])) &
                                  (pd.to_numeric(old["timestamp_sinal"], errors="coerce") == int(row["timestamp_sinal"]))).any())
            if duplicado:
                registrar_sinal_resultado(padrao)
                return
        except Exception:
            pass
    pd.DataFrame([row]).to_csv(arquivo, mode="a", header=not os.path.exists(arquivo), index=False)
    registrar_sinal_resultado(padrao)


# ------------------------- SINAIS NOVOS -------------------------
def emitir_sinal_novo(padrao, filtros, timestamp):
    # A confluência definida pelo usuário é a autorização final. Os filtros
    # legados não devem bloquear um sinal que já passou nos critérios obrigatórios.
    confluencia = filtros.get("confluencia_total")
    liberado = (bool(confluencia.get("liberado"))
                if isinstance(confluencia, dict)
                else bool(filtros.get("aprovado")))
    if (not padrao.get("detectado") or not liberado
            or str(padrao.get("direcao", "")).upper() not in ("CALL", "PUT")):
        return

    chave = (ATIVO, padrao["padrao"], int(timestamp))
    if chave in ULTIMOS_SINAIS:
        return

    agora = time.time()
    chave_tempo = (ATIVO, padrao["padrao"], "tempo")
    anterior = ULTIMOS_SINAIS.get(chave_tempo, 0)
    if agora - anterior < COOLDOWN_SINAL:
        return

    ULTIMOS_SINAIS[chave] = True
    ULTIMOS_SINAIS[chave_tempo] = agora
    direcao_sinal = str(padrao.get("direcao", "")).upper()
    codigo = VERDE if direcao_sinal == "CALL" else VERMELHO
    rotulo = "COMPRA (CALL)" if direcao_sinal == "CALL" else "VENDA (PUT)"
    print("\n" + cor(
        f"NOVO SINAL DE {rotulo}: {padrao['padrao']} | PRECO DE REFERENCIA {fmt(padrao.get('preco_sinal', np.nan))}",
        codigo
    ))
    if filtros.get("angular_disponivel"):
        situacao_angular = "ALINHADA" if filtros.get("angular_ok") else "DIVERGENTE"
        print(f"Projecao angular: {situacao_angular} | Direcao angular: {filtros.get('angular_direcao')} | Pontuacao contextual: {filtros.get('pontuacao', 0)}/6")
    else:
        print("Projecao angular: NEUTRA/INDISPONIVEL; nao confirmou a direcao.")
    print("Sinal tecnico somente leitura; nenhuma ordem enviada.")


# ---------------- ALERTA ANTECIPADO NO 3o CANDLE -----------------
def obter_candle_em_formacao(api):
    """Obtém candle real ainda em formação diretamente da API; nunca o usa para confirmação."""
    agora = time.time()
    dados = api.get_candles(ATIVO, INTERVALO, 3, agora)
    if not dados:
        return None
    bruto = pd.DataFrame(dados)
    obrigatorias = {"open", "close", "min", "max", "from", "to"}
    if not obrigatorias.issubset(bruto.columns):
        return None
    for k in obrigatorias:
        bruto[k] = pd.to_numeric(bruto[k], errors="coerce")
    bruto = bruto.dropna(subset=list(obrigatorias)).sort_values("from")
    # O candle em formação tem horário final ainda no futuro (ou igual ao agora).
    vivos = bruto[bruto["to"] >= agora]
    if vivos.empty:
        return None
    c = vivos.iloc[-1].copy()
    if (float(c["open"]) <= 0 or float(c["close"]) <= 0 or
        float(c["min"]) <= 0 or float(c["max"]) < float(c["min"]) or
        float(c["max"]) < max(float(c["open"]), float(c["close"])) or
        float(c["min"]) > min(float(c["open"]), float(c["close"]))):
        return None
    return c


def verificar_alerta_antecipado(api, df_fechado):
    """Alerta provisório durante o 3o candle. A confirmação usa só candles fechados."""
    global ULTIMO_ALERTA_ANTECIPADO
    try:
        vivo = obter_candle_em_formacao(api)
        if vivo is None or len(df_fechado) < 3:
            return
        # O terceiro candle provisório é combinado com os dois candles fechados anteriores.
        base = df_fechado.tail(2).copy()
        linha = {col: np.nan for col in df_fechado.columns}
        for k in ("open", "close", "min", "max", "from", "to"):
            linha[k] = float(vivo[k])
        linha["atr"] = float(df_fechado.iloc[-1].get("atr", np.nan))
        trio = pd.concat([base, pd.DataFrame([linha])], ignore_index=True)
        soldados = detectar_tres_soldados(trio)
        corvos = detectar_tres_corvos(trio)
        nivel = df_fechado.iloc[-1].get("fib_618", np.nan)
        if pd.isna(nivel) or not np.isfinite(float(nivel)):
            return
        nivel = float(nivel)
        anteriores = df_fechado["close"].tail(4).astype(float).tolist()
        atual = float(vivo["close"])
        # O rompimento pode ter sido confirmado por fechamento recente ou estar acontecendo agora.
        cruzou_call = any(x <= nivel and y > nivel for x, y in zip(anteriores[:-1], anteriores[1:])) or (anteriores[-1] <= nivel < atual)
        cruzou_put = any(x >= nivel and y < nivel for x, y in zip(anteriores[:-1], anteriores[1:])) or (anteriores[-1] >= nivel > atual)
        if soldados["detectado"] and cruzou_call:
            direcao, nome = "CALL", "TRES SOLDADOS"
        elif corvos["detectado"] and cruzou_put:
            direcao, nome = "PUT", "TRES CORVOS"
        else:
            return
        inicio = int(vivo["from"])
        chave = (direcao, inicio)
        if ULTIMO_ALERTA_ANTECIPADO.get(direcao) == chave:
            return
        ULTIMO_ALERTA_ANTECIPADO[direcao] = chave
        # Cores exclusivas do alerta antecipado: azul=compra, roxo=venda.
        # O restante do painel mantém suas cores originais; não colore a tela inteira.
        codigo = AZUL if direcao == "CALL" else ROXO
        print("\n" + cor(f"ALERTA ANTECIPADO PROVISORIO: {nome} | {direcao}", codigo))
        print(cor(f"Rompimento Fibonacci 61.8% observado | nivel={nivel:.5f} | preco atual={atual:.5f}", codigo))
        print("O terceiro candle ainda está aberto: o padrão pode desaparecer. Não é confirmação nem ordem.")
    except Exception:
        # Falha no dado ao vivo não pode virar sinal; a análise de candles fechados continua.
        return



def emitir_sinal_estrutural(padrao):
    """Imprime rompimentos estruturais CALL/PUT confirmados por candle fechado."""
    if not padrao or not padrao.get("detectado") or str(padrao.get("direcao", "")).upper() not in ("CALL", "PUT"):
        return
    if padrao.get("estado") not in ("CONFIRMADO_ROMPIMENTO_PESCOCO", "ROMPIMENTO_FAIXA_CONFIRMADO"):
        return
    ts = int(padrao.get("timestamp_sinal", 0))
    chave = (ATIVO, str(padrao.get("nome")), ts)
    if chave in ULTIMOS_SINAIS:
        return
    ULTIMOS_SINAIS[chave] = True
    codigo = VERDE if padrao.get("direcao") == "CALL" else VERMELHO
    print("\n" + cor(f"ROMPIMENTO CONFIRMADO: {padrao.get('nome')} | {padrao.get('direcao')}", codigo))
    print(f"Fechamento: {fmt(padrao.get('preco_sinal'))} | Estado: {padrao.get('estado')}")
    if padrao.get("linha_pescoco") is not None:
        print(f"Linha de pescoco rompida: {fmt(padrao.get('linha_pescoco'))}")
    else:
        print(f"Faixa rompida: {fmt(padrao.get('limite_inferior'))} - {fmt(padrao.get('limite_superior'))}")
    print("Sinal técnico informativo; não garante continuidade. Nenhuma ordem enviada.")


def imprimir_radar_estrutura(padrao, estatisticas):
    """Exibe diagnóstico de topo/fundo duplo e validação histórica sem enviar ordens."""
    print("\n" + "-" * 68)
    print("RADAR ESTRUTURAL | TOPOS/FUNDOS DUPLOS + ELLIOTT + HISTORICO")
    if padrao and padrao.get("detectado"):
        codigo=VERMELHO if padrao.get("direcao")=="PUT" else VERDE
        print(cor(f"{padrao.get('nome')} | {padrao.get('direcao')} | {padrao.get('estado')}",codigo))
        print(f"Pivo 1: {fmt(padrao.get('pivo1_preco'))} | Pivo 2: {fmt(padrao.get('pivo2_preco'))} | tolerancia: {fmt(padrao.get('tolerancia_preco'))}")
        print(f"Linha de pescoco: {fmt(padrao.get('linha_pescoco'))} | preco sinal: {fmt(padrao.get('preco_sinal'))} | alvo estrutural teorico: {fmt(padrao.get('alvo_teorico'))}")
        print(f"Rejeicao: {padrao.get('rejeicao')} | rompimento pescoco: {padrao.get('rompimento_pescoco')}")
        print(padrao.get("observacao",""))
    else:
        print(f"Topo/fundo duplo: {padrao.get('estado','SEM_PADRAO') if padrao else 'SEM_DADOS'}")
    if estatisticas:
        taxa=estatisticas.get("taxa",np.nan)
        taxa_txt=f"{taxa:.1f}%" if np.isfinite(taxa) else "N/D"
        print(f"Validacoes encerradas nesta rodada: {estatisticas.get('resolvidos',0)} | amostras validadas: {estatisticas.get('amostras',0)} | excursao favoravel maior que contraria: {taxa_txt}")
    print("Resultados são estatísticas retrospectivas; não representam probabilidade garantida nem ordem.")


# ------------------------- PROCESSAMENTO ------------------------
def validar_rompimento_fib618(df, direcao):
    """Exige rompimento do Fibonacci 61.8% na direcao do padrao.

    Usa somente candles fechados reais. Para evitar considerar um simples
    preco acima/abaixo sem rompimento identificavel, procura cruzamento de
    fechamento nos ultimos quatro candles (candle anterior + os tres do padrao),
    usando o nivel 61.8 calculado pela estrutura Fibonacci atual. A validação
    final só roda após o fechamento do terceiro candle do padrão.
    """
    if df is None or len(df) < 4:
        return False, "Dados insuficientes para confirmar rompimento do 61.8%."

    nivel = df.iloc[-1].get("fib_618", np.nan)
    if pd.isna(nivel) or not np.isfinite(float(nivel)):
        return False, "Nivel Fibonacci 61.8% indisponivel; sinal bloqueado."
    nivel = float(nivel)
    fechamentos = df["close"].iloc[-4:].astype(float).to_list()

    if direcao == "CALL":
        cruzou = any(antes <= nivel and depois > nivel
                     for antes, depois in zip(fechamentos[:-1], fechamentos[1:]))
        return cruzou, ("Rompimento do 61.8% para CIMA confirmado." if cruzou
                        else f"Aguardando rompimento do 61.8% para CIMA ({nivel:.5f}).")
    if direcao == "PUT":
        cruzou = any(antes >= nivel and depois < nivel
                     for antes, depois in zip(fechamentos[:-1], fechamentos[1:]))
        return cruzou, ("Rompimento do 61.8% para BAIXO confirmado." if cruzou
                        else f"Aguardando rompimento do 61.8% para BAIXO ({nivel:.5f}).")
    return False, "Direcao do padrao indefinida; sinal bloqueado."


def bloquear_padrao_sem_rompimento(padrao, motivo):
    """Mantem o diagnostico, mas impede sinal se 61.8% nao foi rompido."""
    padrao["motivos"].append(motivo)
    padrao["detectado"] = False
    padrao["padrao"] = "AGUARDANDO ROMPIMENTO FIB 61.8"
    padrao["direcao"] = "NENHUMA"
    return padrao


def analisar_pernada_dinamica(df, preco_atual=None, lado_pivo=2):
    """Avalia continuamente a pernada atual usando pivôs confirmados e preço real.

    Os pivôs vêm exclusivamente de candles H4 reais e fechados. O preço vivo, se
    fornecido, serve apenas para medir a evolução da pernada em andamento; não cria
    candles nem autoriza sinais.
    """
    vazio = {
        "direcao": "INDEFINIDA", "estado": "DADOS INSUFICIENTES",
        "pivo_tipo": "N/D", "pivo_preco": np.nan, "pivo_timestamp": None,
        "preco_referencia": np.nan, "amplitude": np.nan,
        "amplitude_anterior": np.nan, "progresso_pct": np.nan,
        "distancia_atr": np.nan, "barras_pernada": 0,
        "pivos_confirmados": 0, "mensagem": "Aguardando pivôs suficientes."
    }
    if df is None or len(df) < 2 * lado_pivo + 8:
        return vazio.copy()
    base = df.tail(120).reset_index(drop=True)
    highs = pd.to_numeric(base["max"], errors="coerce").to_numpy(float)
    lows = pd.to_numeric(base["min"], errors="coerce").to_numpy(float)
    times = pd.to_numeric(base["to"], errors="coerce").to_numpy(float)
    pivots = []
    # Pivô confirmado: só é registrado quando existem lado_pivo candles fechados à direita.
    for i in range(lado_pivo, len(base) - lado_pivo):
        win_h = highs[i-lado_pivo:i+lado_pivo+1]
        win_l = lows[i-lado_pivo:i+lado_pivo+1]
        if np.isfinite(highs[i]) and highs[i] >= np.nanmax(win_h) and np.count_nonzero(win_h == highs[i]) == 1:
            pivots.append({"idx": i, "tipo": "TOPO", "preco": float(highs[i]), "ts": int(times[i])})
        if np.isfinite(lows[i]) and lows[i] <= np.nanmin(win_l) and np.count_nonzero(win_l == lows[i]) == 1:
            pivots.append({"idx": i, "tipo": "FUNDO", "preco": float(lows[i]), "ts": int(times[i])})
    pivots.sort(key=lambda x: (x["idx"], 0 if x["tipo"] == "FUNDO" else 1))
    # Se um candle for simultaneamente topo/fundo, mantém o mais recente, evitando
    # inventar a ordem intrabarra que os OHLC não revelam.
    compact = []
    for pv in pivots:
        if compact and compact[-1]["idx"] == pv["idx"]:
            compact[-1] = pv
        elif compact and compact[-1]["tipo"] == pv["tipo"]:
            # Entre pivôs consecutivos do mesmo tipo, conserva o extremo mais forte.
            prev = compact[-1]
            mais_extremo = (pv["preco"] > prev["preco"] if pv["tipo"] == "TOPO" else pv["preco"] < prev["preco"])
            if mais_extremo:
                compact[-1] = pv
        else:
            compact.append(pv)
    if len(compact) < 2:
        return {**vazio, "pivos_confirmados": len(compact), "estado": "AGUARDANDO PIVOS CONFIRMADOS"}

    anterior, ultimo = compact[-2], compact[-1]
    preco = float(preco_atual) if preco_atual is not None and np.isfinite(float(preco_atual)) else float(base.iloc[-1]["close"])
    atr = float(base.iloc[-1].get("atr", np.nan))
    if not np.isfinite(preco) or preco <= 0:
        preco = float(base.iloc[-1]["close"])
    if ultimo["tipo"] == "FUNDO":
        direcao = "ALTA" if preco >= ultimo["preco"] else "BAIXA"
        amplitude = preco - ultimo["preco"]
    else:
        direcao = "BAIXA" if preco <= ultimo["preco"] else "ALTA"
        amplitude = ultimo["preco"] - preco
    amplitude_anterior = abs(ultimo["preco"] - anterior["preco"])
    progresso = abs(amplitude) / amplitude_anterior * 100 if amplitude_anterior > 0 else np.nan
    dist_atr = abs(amplitude) / atr if np.isfinite(atr) and atr > 0 else np.nan
    barras = max(0, len(base) - 1 - ultimo["idx"])
    if amplitude < 0:
        estado = "PRECO ATRAVESSOU O PIVO — POSSIVEL INVALIDACAO"
    elif np.isfinite(progresso) and progresso < 25:
        estado = "INICIO DA PERNADA"
    elif np.isfinite(progresso) and progresso < 60:
        estado = "PERNADA EM DESENVOLVIMENTO"
    elif np.isfinite(progresso) and progresso < 85:
        estado = "PERNADA AVANCADA — RISCO DE ATRASO"
    else:
        estado = "PERNADA MUITO ESTENDIDA / POSSIVEL EXAUSTAO"
    msg = (f"{direcao} desde {ultimo['tipo']} {ultimo['preco']:.5f}; "
           f"movimento {abs(amplitude):.5f}; {progresso:.0f}% da pernada anterior" if np.isfinite(progresso)
           else f"{direcao} desde {ultimo['tipo']} {ultimo['preco']:.5f}; amplitude anterior indisponivel")
    return {
        "direcao": direcao, "estado": estado, "pivo_tipo": ultimo["tipo"],
        "pivo_preco": float(ultimo["preco"]), "pivo_timestamp": int(ultimo["ts"]),
        "preco_referencia": preco, "amplitude": abs(float(amplitude)),
        "amplitude_anterior": float(amplitude_anterior), "progresso_pct": float(progresso) if np.isfinite(progresso) else np.nan,
        "distancia_atr": float(dist_atr) if np.isfinite(dist_atr) else np.nan,
        "barras_pernada": int(barras), "pivos_confirmados": len(compact),
        "mensagem": msg, "pivos": compact[-6:]
    }


def validar_inicio_topo_fundo(df):
    """Detecta cedo uma possível rejeição no topo/fundo usando candles fechados reais.

    É um diagnóstico antecipado dos bloqueios, não uma garantia de reversão.
    Usa a faixa anterior sem incluir o candle atual na definição do extremo.
    """
    vazio = {
        "detectado": False, "direcao": "NENHUMA", "estado": "SEM_INICIO_TOPO_FUNDO",
        "topo_referencia": np.nan, "fundo_referencia": np.nan,
        "score": 0, "motivos": [], "bloqueios": []
    }
    if df is None or len(df) < 15:
        return {**vazio, "estado": "DADOS_INSUFICIENTES"}

    a = df.iloc[-1]
    atr = float(a.get("atr", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        return {**vazio, "estado": "ATR_INDISPONIVEL"}

    # 12 candles fechados anteriores; não usa dados futuros nem o candle em formação.
    base = df.iloc[-13:-1]
    if len(base) < 12:
        return {**vazio, "estado": "DADOS_INSUFICIENTES"}

    topo = float(base["max"].max())
    fundo = float(base["min"].min())
    o, c = float(a["open"]), float(a["close"])
    h, l = float(a["max"]), float(a["min"])
    anterior = float(df.iloc[-2]["close"])
    amplitude = max(h - l, 1e-12)
    corpo = abs(c - o)
    pavio_sup = h - max(o, c)
    pavio_inf = min(o, c) - l
    perto_topo = (topo - h) <= 0.25 * atr and h >= topo - 0.25 * atr
    perto_fundo = (l - fundo) <= 0.25 * atr and l <= fundo + 0.25 * atr

    # Rejeição inicial: proximidade do extremo + pavio/candle de retorno.
    rejeicao_topo = perto_topo and (
        (pavio_sup >= max(0.25 * amplitude, 0.08 * atr) and c < h - 0.35 * amplitude)
        or (c < o and c < anterior)
    )
    rejeicao_fundo = perto_fundo and (
        (pavio_inf >= max(0.25 * amplitude, 0.08 * atr) and c > l + 0.35 * amplitude)
        or (c > o and c > anterior)
    )

    # Filtros informam se o bloqueio está perdendo força; não exigimos que
    # todos os indicadores já tenham virado, pois isso costuma ocorrer tarde.
    rsi = float(a.get("rsi", np.nan))
    di_pos = float(a.get("di_positivo", np.nan))
    di_neg = float(a.get("di_negativo", np.nan))
    mom = float(a.get("momentum", np.nan))
    ema3 = float(a.get("ema3", np.nan))
    ema30 = float(a.get("ema30", np.nan))
    motivos_topo = []
    motivos_fundo = []
    if perto_topo: motivos_topo.append("preço encostou no topo recente")
    if perto_fundo: motivos_fundo.append("preço encostou no fundo recente")
    if pavio_sup / amplitude >= 0.25: motivos_topo.append("pavio superior/rejeição")
    if pavio_inf / amplitude >= 0.25: motivos_fundo.append("pavio inferior/rejeição")
    if np.isfinite(rsi) and rsi >= 60: motivos_topo.append(f"RSI favorece exaustão ({rsi:.1f})")
    if np.isfinite(rsi) and rsi <= 40: motivos_fundo.append(f"RSI favorece exaustão ({rsi:.1f})")
    if np.isfinite(di_neg) and np.isfinite(di_pos) and di_neg > di_pos: motivos_topo.append("DI- começou a superar DI+")
    if np.isfinite(di_pos) and np.isfinite(di_neg) and di_pos > di_neg: motivos_fundo.append("DI+ começou a superar DI-")
    if np.isfinite(mom) and mom < 0: motivos_topo.append("Momentum virou/está negativo")
    if np.isfinite(mom) and mom > 0: motivos_fundo.append("Momentum virou/está positivo")
    if np.isfinite(ema3) and np.isfinite(ema30) and ema3 < ema30: motivos_topo.append("EMA3 abaixo da EMA30")
    if np.isfinite(ema3) and np.isfinite(ema30) and ema3 > ema30: motivos_fundo.append("EMA3 acima da EMA30")

    score_topo = int(perto_topo) + int(rejeicao_topo) + int(np.isfinite(rsi) and rsi >= 60) + int(np.isfinite(di_neg) and np.isfinite(di_pos) and di_neg > di_pos) + int(np.isfinite(mom) and mom < 0) + int(np.isfinite(ema3) and np.isfinite(ema30) and ema3 < ema30)
    score_fundo = int(perto_fundo) + int(rejeicao_fundo) + int(np.isfinite(rsi) and rsi <= 40) + int(np.isfinite(di_pos) and np.isfinite(di_neg) and di_pos > di_neg) + int(np.isfinite(mom) and mom > 0) + int(np.isfinite(ema3) and np.isfinite(ema30) and ema3 > ema30)

    # Necessário extremo + rejeição e pelo menos um indício complementar.
    if rejeicao_topo and score_topo >= 2 and score_topo > score_fundo:
        return {
            "detectado": True, "direcao": "PUT", "estado": "INICIO_DE_TOPO_EM_VALIDACAO",
            "topo_referencia": topo, "fundo_referencia": fundo, "score": score_topo,
            "motivos": motivos_topo, "bloqueios": [],
            "timestamp": int(a["to"]), "preco": c, "atr": atr
        }
    if rejeicao_fundo and score_fundo >= 2 and score_fundo > score_topo:
        return {
            "detectado": True, "direcao": "CALL", "estado": "INICIO_DE_FUNDO_EM_VALIDACAO",
            "topo_referencia": topo, "fundo_referencia": fundo, "score": score_fundo,
            "motivos": motivos_fundo, "bloqueios": [],
            "timestamp": int(a["to"]), "preco": c, "atr": atr
        }

    return {
        **vazio, "estado": "AGUARDANDO_REJEICAO_INICIAL",
        "topo_referencia": topo, "fundo_referencia": fundo,
        "score_topo": score_topo, "score_fundo": score_fundo,
        "motivos": motivos_topo if perto_topo else motivos_fundo
    }



def detectar_sinal_somente_topos_fundos(df, janela=12):
    """Sinal baseado exclusivamente na estrutura de topos/fundos e rejeição.

    Usa apenas candles reais fechados. Não consulta RSI, EMA, ADX/DI,
    Momentum, Fibonacci, Elliott, projeção angular ou padrões de candle nomeados.
    """
    vazio = {
        "detectado": False, "padrao": "AGUARDANDO TOPO/FUNDO",
        "direcao": "NENHUMA", "motivos": [], "qualidade_estrutura": "N/D",
        "preco_sinal": np.nan, "referencia_topo": np.nan,
        "referencia_fundo": np.nan, "estado_estrutura": "SEM CONFIRMACAO"
    }
    if df is None or len(df) < janela + 2:
        return {**vazio, "motivos": ["Dados insuficientes para comparar topos e fundos."]}

    # Último candle fechado e janela anterior, sem incluir o candle avaliado.
    atual = df.iloc[-1]
    base = df.iloc[-(janela + 1):-1]
    try:
        o, h, l, c = (float(atual[k]) for k in ("open", "max", "min", "close"))
        topo = float(base["max"].max())
        fundo = float(base["min"].min())
        prev_c = float(df.iloc[-2]["close"])
    except (KeyError, TypeError, ValueError):
        return {**vazio, "motivos": ["Colunas OHLC inválidas."]}

    amplitude_janela = topo - fundo
    amplitude_candle = max(h - l, 1e-12)
    if not np.isfinite(amplitude_janela) or amplitude_janela <= 0:
        return {**vazio, "motivos": ["Faixa de topo/fundo inválida."]}

    # Faixa de proximidade proporcional à estrutura local, não a indicador.
    zona = amplitude_janela * 0.15
    perto_topo = h >= topo - zona
    perto_fundo = l <= fundo + zona
    pavio_sup = h - max(o, c)
    pavio_inf = min(o, c) - l
    rejeicao_topo = perto_topo and (c < o or c < prev_c) and pavio_sup >= amplitude_candle * 0.20
    rejeicao_fundo = perto_fundo and (c > o or c > prev_c) and pavio_inf >= amplitude_candle * 0.20

    # Se ambos os extremos parecem válidos no mesmo candle, não forçar direção.
    if rejeicao_topo and rejeicao_fundo:
        return {**vazio, "referencia_topo": topo, "referencia_fundo": fundo,
                "motivos": ["Rejeição ambígua: topo e fundo candidatos no mesmo candle."]}

    if rejeicao_topo:
        return {
            **vazio, "detectado": True, "padrao": "REJEIÇÃO DE TOPO",
            "direcao": "PUT", "preco_sinal": c,
            "referencia_topo": topo, "referencia_fundo": fundo,
            "qualidade_estrutura": "TOPO EM FORMAÇÃO",
            "estado_estrutura": "REJEIÇÃO NO TOPO",
            "motivos": ["Preço testou o topo da janela", "Candle fechado rejeitou a região superior"]
        }
    if rejeicao_fundo:
        return {
            **vazio, "detectado": True, "padrao": "REJEIÇÃO DE FUNDO",
            "direcao": "CALL", "preco_sinal": c,
            "referencia_topo": topo, "referencia_fundo": fundo,
            "qualidade_estrutura": "FUNDO EM FORMAÇÃO",
            "estado_estrutura": "REJEIÇÃO NO FUNDO",
            "motivos": ["Preço testou o fundo da janela", "Candle fechado rejeitou a região inferior"]
        }

    motivo = "Aguardando rejeição confirmada em um extremo da estrutura."
    if perto_topo:
        motivo = "Preço próximo do topo, mas a rejeição ainda não confirmou."
    elif perto_fundo:
        motivo = "Preço próximo do fundo, mas a rejeição ainda não confirmou."
    return {**vazio, "referencia_topo": topo, "referencia_fundo": fundo,
            "motivos": [motivo], "estado_estrutura": "AGUARDANDO REJEIÇÃO"}

def validar_confluencia_total(df, padrao, fibonacci, elliott, primeiro_alvo, radar_estrutura):
    """Autorização baseada somente em topos/fundos; módulos antigos não bloqueiam."""
    estrut = padrao or {}
    detectado = bool(estrut.get("detectado"))
    direcao = str(estrut.get("direcao", "NENHUMA")).upper()
    ok = detectado and direcao in ("CALL", "PUT") and str(estrut.get("padrao", "")).upper() in ("REJEIÇÃO DE TOPO", "REJEIÇÃO DE FUNDO")
    return {
        "liberado": bool(ok),
        "direcao": direcao if ok else "NENHUMA",
        "criterios": {"REJEIÇÃO EM TOPO/FUNDO": bool(ok)},
        "informativos": {}, "estados_auxiliares": {},
        "pontos_apoio": 0, "pontos_contrarios": 0,
        "falhas": [] if ok else ["AGUARDANDO REJEIÇÃO EM TOPO/FUNDO"],
        "angular": {}, "inicio_topo_fundo": estrut,
        "radar_inicio_extremo_ok": bool(ok), "radar_confirmado_ok": False,
    }

    """Recalcula a confluência a cada candle fechado.

    Os quatro critérios centrais continuam obrigatórios. Fibonacci e Elliott são
    avaliados dinamicamente como confirmações auxiliares: entram no placar e no
    diagnóstico, mas a falta de pivôs/níveis não bloqueia sozinha o sinal.
    """
    direcao = str((padrao or {}).get("direcao", "NENHUMA")).upper()
    nome_padrao = str((padrao or {}).get("padrao", "")).upper()
    padrao_ok = bool((padrao or {}).get("detectado")) and direcao in ("CALL", "PUT")

    # Projeção angular recalculada sobre os candles reais fechados atuais.
    angular = calcular_projecao_angular(df)
    inicio_extremo = validar_inicio_topo_fundo(df)
    # No início de topo/fundo, aceitamos alinhamento angular parcial (2 de 3
    # janelas) em vez de esperar as três janelas alinharem no fim da pernada.
    angular_ok = (
        direcao in ("CALL", "PUT")
        and angular.get("direcao") == direcao
        and angular.get("alinhamento") in ("ALINHADAS", "PARCIAL")
    )

    radar_dir = str((radar_estrutura or {}).get("direcao", "NENHUMA")).upper()
    radar_confirmado_ok = (
        direcao in ("CALL", "PUT")
        and bool((radar_estrutura or {}).get("detectado"))
        and radar_dir == direcao
    )
    # O radar de início de extremo pode validar o critério estrutural antes do
    # rompimento da linha de pescoço. A direção precisa coincidir com o padrão.
    radar_inicio_ok = (
        direcao in ("CALL", "PUT")
        and bool(inicio_extremo.get("detectado"))
        and str(inicio_extremo.get("direcao", "NENHUMA")).upper() == direcao
    )
    radar_ok = radar_confirmado_ok or radar_inicio_ok

    alvo_ok = (direcao in ("CALL", "PUT")
               and str((primeiro_alvo or {}).get("estado", "")).upper() == "ALVO SELECIONADO"
               and str((primeiro_alvo or {}).get("direcao", "NENHUMA")).upper() == direcao)

    # Fibonacci: leitura adaptativa à estrutura atual; não é bloqueio obrigatório.
    fib = fibonacci or {}
    fib_dir = str(fib.get("direcao", "N/D")).upper()
    direcao_fib_esperada = "ALTA" if direcao == "CALL" else "BAIXA"
    fib_direcao_alinhada = direcao in ("CALL", "PUT") and fib_dir == direcao_fib_esperada
    fib_valido = bool(fib.get("valido"))
    fib_extremo_contra = bool(fib.get("rompeu_786")) or bool(fib.get("rompeu_918"))
    fib_suporte = fib_valido and fib_direcao_alinhada and not fib_extremo_contra
    fib_contra = fib_valido and (not fib_direcao_alinhada or fib_extremo_contra)
    fib_estado = ("A FAVOR" if fib_suporte else "CONTRA/ESTRUTURA ESTICADA" if fib_contra
                  else "INDEFINIDO — DADOS INSUFICIENTES")

    # Elliott: hipótese por pivôs confirmados; confiança moderada/alta aumenta suporte.
    ell = elliott or {}
    ell_dir = str(ell.get("direcao", "N/D")).upper()
    ell_state = str(ell.get("estado", "")).upper()
    ell_conf = str(ell.get("confianca", "BAIXA")).upper()
    ell_direcao_alinhada = ell_dir == direcao_fib_esperada and direcao in ("CALL", "PUT")
    ell_impulso = ell_state in ("POSSIVEL IMPULSO", "POSSÍVEL IMPULSO", "IMPULSO")
    ell_suporte = ell_direcao_alinhada and ell_impulso and ell_conf in ("MODERADA", "ALTA")
    ell_contra = ell_dir in ("ALTA", "BAIXA") and not ell_direcao_alinhada
    ell_estado = ("A FAVOR" if ell_suporte else "CONTRA" if ell_contra
                  else "INDEFINIDO — HIPÓTESE NÃO CONFIRMADA")

    criterios = {
        "PADRAO SELECIONADO": padrao_ok,
        "RADAR ESTRUTURAL": radar_ok,
        "PROJECAO ANGULAR": angular_ok,
        "CONTROLE DO PRIMEIRO ALVO": alvo_ok,
    }
    # Placar auxiliar dinâmico (não substitui os critérios centrais obrigatórios).
    apoios = {"FIBONACCI": fib_suporte, "ELLIOTT": ell_suporte}
    pontos_apoio = sum(1 for ok in apoios.values() if ok)
    pontos_contrarios = int(fib_contra) + int(ell_contra)
    falhas = [nome for nome, ok in criterios.items() if not ok]
    return {
        "liberado": not falhas,
        "direcao": direcao if not falhas else "NENHUMA",
        "criterios": criterios,
        "informativos": {"FIBONACCI": fib_suporte, "ONDAS DE ELLIOTT": ell_suporte},
        "estados_auxiliares": {"FIBONACCI": fib_estado, "ONDAS DE ELLIOTT": ell_estado},
        "pontos_apoio": pontos_apoio,
        "pontos_contrarios": pontos_contrarios,
        "falhas": falhas,
        "angular": angular,
        "inicio_topo_fundo": inicio_extremo,
        "radar_inicio_extremo_ok": radar_inicio_ok,
        "radar_confirmado_ok": radar_confirmado_ok,
    }


def atualizar_leitura_dinamica_preco(api, df_fechado):
    """Atualiza a leitura com o preço real da vela ainda aberta, sem fabricar candle.

    O preço vivo serve para recalcular distância a Fibonacci, inclinação angular,
    posição perante a estrutura e distância até o alvo. A emissão de sinal permanece
    restrita a padrões e confirmações de candles fechados.
    """
    global ULTIMA_LINHA_PRECO_DINAMICO, ULTIMA_PERNADA_DINAMICA
    try:
        vivo = obter_candle_em_formacao(api)
        if vivo is None or df_fechado is None or len(df_fechado) < max(ANGULAR_JANELAS):
            return
        preco = float(vivo["close"])
        if not np.isfinite(preco) or preco <= 0:
            return

        a = df_fechado.iloc[-1]
        atr = float(a.get("atr", np.nan))
        if not np.isfinite(atr) or atr <= 0:
            return
        variacao = preco - float(a["close"])
        variacao_atr = variacao / atr
        mov = "SUBINDO" if variacao > 0 else "DESCENDO" if variacao < 0 else "ESTAVEL"
        # Recalcula a pernada a cada leitura de preço real (a cada ciclo do loop).
        ULTIMA_PERNADA_DINAMICA = analisar_pernada_dinamica(df_fechado, preco)
        per = ULTIMA_PERNADA_DINAMICA
        per_txt = (f"PERNADA {per.get('direcao','N/D')} | {per.get('estado','N/D')} | "
                   f"{per.get('progresso_pct', np.nan):.0f}%" if np.isfinite(per.get("progresso_pct", np.nan))
                   else f"PERNADA {per.get('direcao','N/D')} | {per.get('estado','N/D')}")

        # Fibonacci é calculada com os candles fechados; a posição/distância é atualizada
        # com a cotação real corrente da API, sem recalcular OHLC artificiais.
        niveis = {}
        for rotulo, campo in (("38.2", "fib_382"), ("50.0", "fib_500"),
                              ("61.8", "fib_618"), ("78.6", "fib_786"),
                              ("91.8", "fib_918")):
            valor = a.get(campo, np.nan)
            if pd.notna(valor) and np.isfinite(float(valor)):
                niveis[rotulo] = float(valor)
        if niveis:
            perto = min(niveis, key=lambda k: abs(preco - niveis[k]))
            dist_fib = abs(preco - niveis[perto])
            fib_txt = f"FIB {perto}%={niveis[perto]:.5f} Δ{dist_fib:.5f}"
            if dist_fib <= FIB_TOLERANCIA_ATR * atr:
                fib_txt += " PROXIMO"
        else:
            fib_txt = "FIB indisponivel"

        # Ângulo vivo: substitui somente a última observação da janela pelo preço real atual.
        closes = pd.to_numeric(df_fechado["close"], errors="coerce").dropna().to_numpy(float)
        angulos = []
        for janela in ANGULAR_JANELAS:
            y = np.concatenate([closes[-(janela-1):], np.array([preco])])
            x = np.arange(len(y), dtype=float)
            slope = float(np.polyfit(x, y, 1)[0])
            ang = float(np.degrees(np.arctan(slope / atr)))
            angulos.append((janela, ang))
        votos_alta = sum(ang >= ANGULAR_LIMIAR_GRAUS for _, ang in angulos)
        votos_baixa = sum(ang <= -ANGULAR_LIMIAR_GRAUS for _, ang in angulos)
        ang_dir = "CALL" if votos_alta >= 2 else "PUT" if votos_baixa >= 2 else "NEUTRA"
        ang_txt = "ANG " + ang_dir + " " + "/".join(f"{ang:+.0f}°" for _, ang in angulos)

        # Radar de preço: distâncias ao topo/fundo dos últimos 20 candles fechados.
        janela = df_fechado.tail(20)
        topo = float(pd.to_numeric(janela["max"], errors="coerce").max())
        fundo = float(pd.to_numeric(janela["min"], errors="coerce").min())
        dist_topo = topo - preco
        dist_fundo = preco - fundo
        if preco > topo:
            radar_txt = "RADAR ROMPIMENTO ALTA"
        elif preco < fundo:
            radar_txt = "RADAR ROMPIMENTO BAIXA"
        elif dist_topo <= dist_fundo:
            radar_txt = f"RADAR resistencia Δ{max(0.0, dist_topo):.5f}"
        else:
            radar_txt = f"RADAR suporte Δ{max(0.0, dist_fundo):.5f}"

        # Elliott permanece baseado em pivôs confirmados; atualiza-se a relação do preço
        # vivo com o último fechamento para mostrar se o preço acompanha a hipótese.
        ell = ULTIMO_CONTEXTO_DINAMICO.get("elliott", {})
        ell_dir = str(ell.get("direcao", "N/D")).upper()
        if ell_dir.startswith("ALTA"):
            ell_live = "PRECO ACOMPANHA" if preco >= float(a["close"]) else "PRECO CONTRA"
        elif ell_dir.startswith("BAIXA"):
            ell_live = "PRECO ACOMPANHA" if preco <= float(a["close"]) else "PRECO CONTRA"
        else:
            ell_live = "SEM DIRECAO CONFIRMADA"
        ell_txt = f"ELLIOTT {ell_dir}/{ell_live}"

        # O alvo selecionado no último candle fechado mantém seu nível, mas a distância
        # até ele é recalculada a cada atualização de preço.
        alvo_ctx = ULTIMO_CONTEXTO_DINAMICO.get("alvo", {})
        if alvo_ctx.get("estado") == "ALVO SELECIONADO" and pd.notna(alvo_ctx.get("alvo", np.nan)):
            alvo = float(alvo_ctx["alvo"])
            alvo_dist = abs(alvo - preco)
            alvo_txt = f"ALVO {alvo_ctx.get('direcao', 'N/D')}={alvo:.5f} Δ{alvo_dist:.5f}"
        else:
            alvo_txt = "ALVO aguardando selecao no fechamento"

        hora_preco = datetime.now().strftime("%H:%M:%S")
        texto = (f"[{hora_preco}] PRECO VIVO {preco:.5f} | {mov} {variacao:+.5f} ({variacao_atr:+.2f} ATR) | "
                 f"{per_txt} | {ang_txt} | {fib_txt} | {radar_txt} | {ell_txt} | {alvo_txt}")
        # Atualiza uma única linha no terminal, evitando uma linha nova a cada 2 segundos.
        padding = " " * max(0, len(ULTIMA_LINHA_PRECO_DINAMICO) - len(texto))
        print("\r" + texto + padding, end="", flush=True)
        ULTIMA_LINHA_PRECO_DINAMICO = texto
    except Exception:
        # Dado vivo ausente/inválido nunca deve produzir preço inventado nem sinal.
        return


def processar(api):
    global ULTIMO_CANDLE, ULTIMO_CONTEXTO_DINAMICO, ULTIMA_LINHA_PRECO_DINAMICO, ULTIMA_PERNADA_DINAMICA

    df_api = obter_candles(api, ATIVO, INTERVALO, QUANTIDADE_CANDLES)
    timestamp = int(df_api.iloc[-1]["to"])

    # Guarda candles reais novos e combina o CSV persistente com os candles atuais.
    # Os cálculos e as projeções passam a usar esse histórico combinado.
    df_combinado = atualizar_historico_candles(df_api)
    df = calcular_indicadores(df_combinado)
    # Pernada recalculada em cada candle fechado novo; durante o candle, o monitor
    # atualiza a distância/progresso usando a cotação real a cada ciclo de 2 segundos.
    ULTIMA_PERNADA_DINAMICA = analisar_pernada_dinamica(df, float(df.iloc[-1]["close"]))

    # SOMENTE ESTAGIO 2: nenhuma leitura de candle em formacao/alerta antecipado.
    # Todos os sinais confirmados usam candles reais já fechados.

    # Painel/CSV/confirmação só atualizam quando existe novo candle fechado.
    if timestamp == ULTIMO_CANDLE:
        atualizar_leitura_dinamica_preco(api, df)
        return

    # Contexto MN1/W1/D1 atualizado com candles reais fechados; se indisponível,
    # o scanner mantém a leitura H4 mas mostra que não há confluência superior confirmada.
    atualizar_contexto_swing(api)

    # Fotografia integral dos 60 candles e registro de pivôs confirmados.
    salvar_snapshot_janela_60(df)
    salvar_pivos_elliott(df)

    # MODO ESTRUTURAL PURO: a direção é definida apenas por rejeição em topo/fundo.
    # Os módulos antigos podem continuar calculados para compatibilidade do painel,
    # mas não participam da decisão nem bloqueiam/liberam sinais.
    soldados = {"detectado": False, "direcao": "NENHUMA", "motivos": []}
    corvos = {"detectado": False, "direcao": "NENHUMA", "motivos": []}
    padrao = detectar_sinal_somente_topos_fundos(df)

    # Fibonacci 61.8% permanece informativo; não é requisito para detectar padrões.
    fib_call_ok, motivo_call = validar_rompimento_fib618(df, "CALL")
    fib_put_ok, motivo_put = validar_rompimento_fib618(df, "PUT")
    if padrao.get("detectado"):
        filtros = {
            "aprovado": True, "ema_ok": True, "di_ok": True,
            "momentum_ok": True, "motivos": list(padrao.get("motivos", [])),
            "bloqueios": [], "modo_analise": "SOMENTE TOPOS E FUNDOS",
            # Campo legado exigido pelo registro CSV; não participa da decisão.
            "esticamento_atr": np.nan, "pontuacao": 0,
            "angular_direcao": "N/D", "angular_ok": False,
            "angular_angulos": {}
        }
        status = "TOPO_FUNDO_DETECTADO"
    else:
        a = df.iloc[-1]
        padrao["padrao"] = "AGUARDANDO TOPO/FUNDO"
        filtros = {
            "aprovado": False, "motivos": list(padrao.get("motivos", [])),
            "bloqueios": [], "modo_analise": "SOMENTE TOPOS E FUNDOS",
            # Campo legado exigido pelo registro CSV; não participa da decisão.
            "esticamento_atr": np.nan, "pontuacao": 0,
            "angular_direcao": "N/D", "angular_ok": False,
            "angular_angulos": {}
        }
        status = "AGUARDANDO_TOPO_FUNDO"

    fibonacci = avaliar_fibonacci(df, padrao.get("direcao", "NENHUMA"))
    elliott = avaliar_ondas_elliott(df)
    # Radar estrutural separado: não substitui nem altera as regras originais 3S3C/Fibonacci 61.8.
    padrao_duplo = detectar_topo_fundo_duplo(df, elliott=elliott, fibonacci=fibonacci)
    registrar_padrao_duplo(padrao_duplo, elliott=elliott, fibonacci=fibonacci)
    padrao_lateral = detectar_rompimento_lateralizacao(df, padrao_duplo=padrao_duplo)
    # Padrão duplo confirmado tem prioridade. Caso contrário, aceita rompimento de faixa
    # somente se não houver topo/fundo duplo válido aguardando sua linha de pescoço.
    sinal_estrutura = padrao_duplo if padrao_duplo.get("detectado") else padrao_lateral
    if padrao_lateral.get("detectado") and not padrao_duplo.get("detectado"):
        registrar_rompimento_lateral(padrao_lateral)
    estat_resultados = atualizar_resultados_sinais(df)
    # A projeção avalia CALL e PUT em separado, sem criar/confirmar padrão 3S3C.
    primeiro_alvo = selecionar_primeiro_alvo(df, fibonacci=fibonacci, elliott=elliott)
    ULTIMO_CONTEXTO_DINAMICO = {"fibonacci": fibonacci, "elliott": elliott, "alvo": primeiro_alvo, "radar": sinal_estrutura}
    # Regra de CONFLUÊNCIA TOTAL: sem alinhamento simultâneo de todos os
    # módulos, o QMS não libera CALL/PUT. O diagnóstico continua visível.
    confluencia = validar_confluencia_total(
        df, padrao, fibonacci, elliott, primeiro_alvo, sinal_estrutura
    )
    filtros["confluencia_total"] = confluencia
    # Filtro swing superior: bloqueia quando MN1, W1 e D1 estão todos
    # claramente contra a direção do sinal H4. Contexto ausente/neutro não é
    # tratado como confirmação nem como oposição.
    if confluencia["liberado"] and padrao.get("direcao") in ("CALL", "PUT"):
        direcao_sinal = "ALTA" if padrao.get("direcao") == "CALL" else "BAIXA"
        dirs_superiores = [CONTEXTO_SWING.get(tf, {}).get("direcao") for tf in ("MN1", "W1", "D1")]
        superiores_contra = sum(d in ("ALTA", "BAIXA") and d != direcao_sinal for d in dirs_superiores)
        if superiores_contra == 3:
            confluencia["liberado"] = False
            confluencia.setdefault("falhas", []).append("MN1, W1 e D1 em conflito com a direção H4")

    if confluencia["liberado"]:
        # A confluência aprovada é a regra final; Fibonacci e Elliott entram
        # dinamicamente como apoios auxiliares e não bloqueiam sozinhos.
        filtros["aprovado"] = True
    else:
        filtros["aprovado"] = False
        filtros.setdefault("bloqueios", []).append(
            "CONFLUENCIA OBRIGATORIA BLOQUEADA: " + ", ".join(confluencia["falhas"])
        )
        filtros.setdefault("motivos", []).append(
            "Sinal não liberado: os quatro critérios obrigatórios precisam concordar."
        )
        if status == "APROVADO":
            status = "BLOQUEADO_CONFLUENCIA_TOTAL"

    # O CSV de validação guarda a seleção; a taxa histórica é calculada somente
    # com candles posteriores reais já fechados, nunca com preços sintéticos.
    registrar_validacao_alvo(timestamp, primeiro_alvo)
    if ULTIMA_LINHA_PRECO_DINAMICO:
        print("\n")
        ULTIMA_LINHA_PRECO_DINAMICO = ""
    emitir_painel(df, soldados, corvos, padrao, filtros, fibonacci, elliott,
                  primeiro_alvo, sinal_estrutura, estat_resultados)
    print("\nCONFLUENCIA OBRIGATORIA: " + ("TODOS OS CRITERIOS OBRIGATORIOS ALINHADOS" if confluencia["liberado"] else "AGUARDAR — " + ", ".join(confluencia["falhas"])))
    salvar_csv(df, padrao, filtros, status, fibonacci, elliott, primeiro_alvo)
    emitir_sinal_novo(padrao, filtros, timestamp)
    # Sinais independentes do radar legado foram desativados: somente topo/fundo decide.
    ULTIMO_CANDLE = timestamp
    atualizar_leitura_dinamica_preco(api, df)


def executar():
    global FALHAS_CONSECUTIVAS, API

    selecionar_padroes_interativo()
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
                    try:
                        API.change_balance(CONTA)
                    except Exception:
                        pass
                    print("Conexao restabelecida.")

                processar(API)
                FALHAS_CONSECUTIVAS = 0

            except KeyboardInterrupt:
                print("\nExecucao encerrada pelo usuario.")
                break

            except Exception as erro:
                FALHAS_CONSECUTIVAS += 1
                print(f"\nFalha {FALHAS_CONSECUTIVAS}/{MAX_FALHAS}: {erro}")
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
