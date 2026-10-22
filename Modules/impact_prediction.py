import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from openpyxl import load_workbook
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss

HDX_PACKAGE_API = "https://data.humdata.org/api/3/action/package_show"
MAX_HORIZONTE_ANOS = 100


def _reportar_progresso(
    callback: Callable[[int, str], None] | None,
    percentual: int,
    mensagem: str,
) -> None:
    if callback:
        callback(max(0, min(100, percentual)), mensagem)


def baixar_emdat_csv(pasta_destino: str | Path) -> dict[str, Any]:
    resposta = requests.get(
        HDX_PACKAGE_API,
        params={"id": "emdat-country-profiles"},
        headers={"User-Agent": "ProjetoFundacao/1.0"},
        timeout=(10, 45),
    )
    resposta.raise_for_status()
    pacote = resposta.json()
    if not pacote.get("success"):
        raise ValueError("A API do HDX não retornou o catálogo EM-DAT Country Profiles.")

    recursos = pacote.get("result", {}).get("resources", [])
    recurso = next(
        (
            item for item in recursos
            if item.get("format", "").casefold() in {"xlsx", "excel"}
            and item.get("download_url")
        ),
        None,
    )
    if recurso is None:
        raise ValueError("O HDX não anunciou um arquivo XLSX baixável para EM-DAT Country Profiles.")

    descricao = recurso.get("description", "")
    versao_encontrada = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", descricao)
    data_recurso = recurso.get("last_modified", "")[:10]
    versao = versao_encontrada.group(1) if versao_encontrada else data_recurso
    if not versao:
        versao = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    destino = Path(pasta_destino)
    destino.mkdir(parents=True, exist_ok=True)
    caminho_csv = destino / f"emdat_country_profiles_{versao.replace('-', '')}.csv"
    caminho_metadados = caminho_csv.with_suffix(".source.json")
    download_url = recurso["download_url"]
    resposta_arquivo = requests.get(
        download_url,
        headers={"User-Agent": "ProjetoFundacao/1.0"},
        timeout=(10, 90),
    )
    resposta_arquivo.raise_for_status()
    conteudo = resposta_arquivo.content
    buffer = io.BytesIO(conteudo)
    if not zipfile.is_zipfile(buffer):
        raise ValueError("A resposta do HDX não é uma planilha XLSX válida.")

    workbook = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    temporario = caminho_csv.with_suffix(".csv.tmp")
    linhas = 0
    try:
        if not workbook.worksheets:
            raise ValueError("A planilha EM-DAT baixada não contém abas.")
        planilha = workbook.active
        planilha.reset_dimensions()
        with temporario.open("w", encoding="utf-8-sig", newline="") as arquivo_csv:
            escritor = csv.writer(arquivo_csv)
            for linha in planilha.iter_rows(values_only=True):
                escritor.writerow([valor if valor is not None else "" for valor in linha])
                linhas += 1
        workbook.close()
        temporario.replace(caminho_csv)
    except Exception:
        workbook.close()
        temporario.unlink(missing_ok=True)
        raise

    metadados = {
        "fonte": "EM-DAT Country Profiles via Humanitarian Data Exchange (HDX)",
        "versao": versao,
        "url_fonte": "https://data.humdata.org/dataset/emdat-country-profiles",
        "url_download": download_url,
        "baixado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "citacao": "EM-DAT, CRED / UCLouvain, Brussels, Belgium -- www.emdat.be",
        "observacao": "Perfil agregado anual por país e subtipo; sujeito aos termos de uso EM-DAT.",
    }
    caminho_metadados.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"caminho": caminho_csv, "versao": versao, "linhas": max(0, linhas - 2), "metadados": caminho_metadados}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").casefold())
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"[^a-z0-9]+", "", texto)


def _ler_csv(caminho: str) -> tuple[list[str], list[dict[str, str]]]:
    with open(caminho, "r", encoding="utf-8-sig", newline="") as arquivo:
        amostra = arquivo.read(8192)
        arquivo.seek(0)
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t")
        except csv.Error:
            dialeto = csv.excel
        leitor = csv.DictReader(arquivo, dialect=dialeto)
        if not leitor.fieldnames:
            raise ValueError(f"O arquivo {Path(caminho).name} não possui cabeçalho CSV.")
        return list(leitor.fieldnames), list(leitor)


def _coluna(cabecalhos: list[str], aliases: tuple[str, ...], obrigatoria: bool = True) -> str | None:
    mapeamento = {_normalizar(nome): nome for nome in cabecalhos}
    for alias in aliases:
        encontrado = mapeamento.get(_normalizar(alias))
        if encontrado:
            return encontrado
    if obrigatoria:
        esperado = ", ".join(aliases)
        raise ValueError(f"Coluna não encontrada. Esperado um destes nomes: {esperado}.")
    return None


def _ano(valor: Any) -> int | None:
    texto = str(valor or "").strip()
    if not texto:
        return None
    correspondencia = re.search(r"(?:18|19|20|21)\d{2}", texto)
    return int(correspondencia.group(0)) if correspondencia else None


def _numero(valor: Any) -> float | None:
    texto = str(valor or "").strip().replace(" ", "")
    if not texto or texto.casefold() in {"nan", "na", "n/a", "null", "-"}:
        return None
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    else:
        texto = texto.replace(",", "")
    try:
        return float(texto)
    except ValueError:
        return None


def _ler_preditores(
    caminho: str,
    tema: str,
    progresso: Callable[[int, str], None] | None = None,
    faixa_progresso: tuple[int, int] = (5, 23),
) -> tuple[dict[tuple[str, int], dict[str, float]], list[str]]:
    cabecalhos, linhas = _ler_csv(caminho)
    coluna_data = _coluna(cabecalhos, ("year", "ano", "date", "data", "time", "period", "periodo"))
   # coluna_local = _coluna(
   #     ("iso3", "iso", "iso code", "country code", "location", "country", "local", "pais", "region", "regiao"),
   # )
    coluna_variavel = _coluna(cabecalhos, ("titulo"))
    coluna_valor = _coluna(cabecalhos, ("titulo"))
    coluna_unidade = _coluna(cabecalhos, ("titulo"), obrigatoria=False)

    termos = [_normalizar(parte) for parte in tema.split() if _normalizar(parte)]
    if not termos:
        raise ValueError("Informe o tema que identifica as variáveis preditoras.")

    valores: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    rotulos: dict[str, str] = {}
    ultimo_percentual = -1
    total_linhas = max(1, len(linhas))
    for indice, linha in enumerate(linhas, start=1):
        percentual = faixa_progresso[0] + (
            (faixa_progresso[1] - faixa_progresso[0]) * indice // total_linhas
        )
        if percentual != ultimo_percentual:
            _reportar_progresso(progresso, percentual, f"Lendo séries preditoras: {indice}/{len(linhas)} linhas.")
            ultimo_percentual = percentual
        variavel = str(linha.get(coluna_variavel) or "").strip()
        variavel_normalizada = _normalizar(variavel)
        if not variavel or not all(termo in variavel_normalizada for termo in termos):
            continue
        ano = _ano(linha.get(coluna_data))
      #  local = _normalizar(linha.get(coluna_local) or "") or "global" 
        local = "global"
        valor = _numero(linha.get(coluna_valor))
        if ano is None or valor is None:
            continue
        unidade = str(linha.get(coluna_unidade) or "").strip()
        chave_variavel = f"{variavel} [{unidade}]" if unidade else variavel
        chave_normalizada = _normalizar(chave_variavel)
        chave = (local, ano, chave_normalizada)
        valores[chave].append(valor)
        rotulos[chave_normalizada] = chave_variavel

    if not valores:
        raise ValueError(f"Nenhuma medição numérica para '{tema}' foi encontrada no CSV preditor.")

    agregados = {chave: sum(amostras) / len(amostras) for chave, amostras in valores.items()}
    series_por_chave: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    variaveis = sorted(rotulos)
    for (local, ano, variavel), valor in agregados.items():
        series_por_chave[(local, ano)][variavel] = valor

    variaveis_validas = [
        variavel for variavel in variaveis
        if len({agregados[chave] for chave in agregados if chave[2] == variavel}) >= 2
    ]
    if not variaveis_validas:
        raise ValueError("As variáveis encontradas não variam; não é possível ajustar um modelo.")
    for valores_ano in series_por_chave.values():
        for variavel in variaveis_validas:
            valores_ano.setdefault(variavel, float("nan"))
    series_por_chave = {
        chave: {variavel: valores[variavel] for variavel in variaveis_validas}
        for chave, valores in series_por_chave.items()
    }
    return series_por_chave, [rotulos[variavel] for variavel in variaveis_validas]


def _ler_eventos(
    caminho: str,
    limite_mortes: float,
    limite_afetados: float,
    limite_prejuizo_usd: float,
    progresso: Callable[[int, str], None] | None = None,
    faixa_progresso: tuple[int, int] = (26, 44),
) -> tuple[set[tuple[str, int]], int, set[str]]:
    cabecalhos, linhas = _ler_csv(caminho)
    coluna_ano = _coluna(cabecalhos, ("start year", "start_year", "year", "ano", "start date", "data inicio"))
  #  coluna_local = _coluna(
  #      cabecalhos,
  #      ("iso3", "iso", "iso code", "country code", "country", "pais", "location", "local"),
   # )
    coluna_mortes = _coluna(cabecalhos, ("total deaths", "total_deaths", "deaths", "mortes"), obrigatoria=False)
    coluna_afetados = _coluna(cabecalhos, ("total affected", "total_affected", "affected", "afetados"), obrigatoria=False)
    coluna_prejuizo = _coluna(
        cabecalhos,
        (
            "total damage (usd, adjusted)", "total damage usd adjusted", "total_damage_usd_adjusted",
            "total damage ('000 us$)", "total damage 000 usd", "total damage usd", "total_damage_usd",
            "total damage",
        ),
        obrigatoria=False,
    )
    if not any((coluna_mortes, coluna_afetados, coluna_prejuizo)):
        raise ValueError("O CSV de impactos precisa conter mortes, afetados ou prejuízo econômico.")

    eventos: set[tuple[str, int]] = set()
    anos = []
    localidades = set()
    totais_por_ano: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"mortes": 0.0, "afetados": 0.0, "prejuizo": 0.0}
    )
    ultimo_percentual = -1
    total_linhas = max(1, len(linhas))
    for indice, linha in enumerate(linhas, start=1):
        percentual = faixa_progresso[0] + (
            (faixa_progresso[1] - faixa_progresso[0]) * indice // total_linhas
        )
        if percentual != ultimo_percentual:
            _reportar_progresso(progresso, percentual, f"Lendo e agregando impactos EM-DAT: {indice}/{len(linhas)} linhas.")
            ultimo_percentual = percentual
        ano = _ano(linha.get(coluna_ano))
      #  local = _normalizar(linha.get(coluna_local) or "") or "global"
        local = "global"
        if ano is None:
            continue
        anos.append(ano)
        localidades.add(local)
        mortes = _numero(linha.get(coluna_mortes)) if coluna_mortes else None
        afetados = _numero(linha.get(coluna_afetados)) if coluna_afetados else None
        prejuizo = _numero(linha.get(coluna_prejuizo)) if coluna_prejuizo else None
        cabecalho_prejuizo = _normalizar(coluna_prejuizo or "")
        if prejuizo is not None and ("000" in cabecalho_prejuizo or "thousand" in cabecalho_prejuizo):
            prejuizo *= 1000
        totais = totais_por_ano[(local, ano)]
        totais["mortes"] += mortes or 0
        totais["afetados"] += afetados or 0
        totais["prejuizo"] += prejuizo or 0

    for chave, totais in totais_por_ano.items():
        if (
            totais["mortes"] >= limite_mortes
            or totais["afetados"] >= limite_afetados
            or totais["prejuizo"] >= limite_prejuizo_usd
        ):
            eventos.add(chave)
    if not anos:
        raise ValueError("O catálogo de impactos não contém anos reconhecíveis.")
    return eventos, max(anos), localidades


def _construir_amostras(
    preditores: dict[tuple[str, int], dict[str, float]],
    eventos: set[tuple[str, int]],
    ultimo_ano_eventos: int,
    horizonte: int,
    progresso: Callable[[int, str], None] | None = None,
    faixa_progresso: tuple[int, int] = (48, 58),
) -> tuple[list[list[float]], list[int], list[int], list[tuple[str, int, dict[str, float]]], list[str]]:
    variaveis = sorted({variavel for dados in preditores.values() for variavel in dados})
    linhas_x: list[list[float]] = []
    linhas_y: list[int] = []
    anos_amostra: list[int] = []
    locais = sorted({local for local, _ in preditores})
    amostras_ordenadas = sorted(preditores.items())
    ultimo_percentual = -1
    total_amostras = max(1, len(amostras_ordenadas))
    for indice, ((local, ano), dados) in enumerate(amostras_ordenadas, start=1):
        percentual = faixa_progresso[0] + (
            (faixa_progresso[1] - faixa_progresso[0]) * indice // total_amostras
        )
        if percentual != ultimo_percentual:
            _reportar_progresso(progresso, percentual, f"Montando amostras país-ano: {indice}/{len(amostras_ordenadas)}.")
            ultimo_percentual = percentual
        if ano + horizonte > ultimo_ano_eventos:
            continue
        rotulo = int(any((local, ano_futuro) in eventos for ano_futuro in range(ano + 1, ano + horizonte + 1)))
        linhas_x.append([dados.get(variavel, float("nan")) for variavel in variaveis])
        linhas_y.append(rotulo)
        anos_amostra.append(ano)
    if not linhas_x:
        raise ValueError("Não há anos com horizonte futuro completo no catálogo de impactos.")
    ultimas = []
    for local in locais:
        candidatos = [(ano, dados) for (local_linha, ano), dados in preditores.items() if local_linha == local]
        if candidatos:
            ano, dados = max(candidatos, key=lambda item: item[0])
            ultimas.append((local, ano, dados))
    return linhas_x, linhas_y, anos_amostra, ultimas, variaveis


def analisar_risco_de_impacto(
    tema: str,
    arquivo_preditores: str,
    arquivo_emdat: str,
    horizonte: int = 1,
    limite_mortes: float = 100,
    limite_afetados: float = 100000,
    limite_prejuizo_usd: float = 1_000_000_000,
    pasta_saida: str | Path | None = None,
    progresso: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    _reportar_progresso(progresso, 0, "Iniciando cruzamento e validando parâmetros/arquivos.")
    if not tema.strip():
        raise ValueError("Informe o tema dos preditores.")
    if not 1 <= horizonte <= MAX_HORIZONTE_ANOS:
        raise ValueError(f"O horizonte deve estar entre 1 e {MAX_HORIZONTE_ANOS} anos.")
    if min(limite_mortes, limite_afetados, limite_prejuizo_usd) < 0:
        raise ValueError("Os limiares de impacto não podem ser negativos.")

    _reportar_progresso(progresso, 3, "Lendo séries quantitativas e filtrando variáveis pelo tema.")
    preditores, nomes_variaveis = _ler_preditores(arquivo_preditores, tema, progresso)
    _reportar_progresso(
        progresso,
        24,
        f"Séries lidas: {len(preditores)} observações país-ano e {len(nomes_variaveis)} variáveis.",
    )
    _reportar_progresso(progresso, 25, "Lendo catálogo EM-DAT e agregando registros por país/ano.")
    eventos, ultimo_ano_eventos, localidades_em_catalogo = _ler_eventos(
        arquivo_emdat, limite_mortes, limite_afetados, limite_prejuizo_usd, progresso
    )
    _reportar_progresso(
        progresso,
        45,
        f"Rótulos de impacto: mortes ≥ {limite_mortes:g} OU afetados ≥ {limite_afetados:g} "
        f"OU prejuízo USD ≥ {limite_prejuizo_usd:g}; {len(eventos)} país-anos positivos.",
    )
    locais_com_preditores = {local for local, _ in preditores}
    locais_compativeis = localidades_em_catalogo & locais_com_preditores
    if not locais_compativeis:
        raise ValueError(
            "Não há localidades em comum entre as séries preditoras e o catálogo de impactos. "
            "Use nomes de países/ISO compatíveis nos dois CSVs."
        )
    preditores = {chave: valor for chave, valor in preditores.items() if chave[0] in locais_compativeis}
    linhas_x, linhas_y, anos_amostra, ultimas, variaveis = _construir_amostras(
        preditores, eventos, ultimo_ano_eventos, horizonte, progresso
    )
    valores_conhecidos = [
        linha for linha in linhas_x if any(valor == valor for valor in linha)
    ]
    if len(valores_conhecidos) < 20:
        raise ValueError("São necessárias pelo menos 20 observações país-ano completas para estimar o modelo.")
    if len(set(linhas_y)) < 2:
        raise ValueError("Os limiares escolhidos não produziram exemplos com e sem impacto. Ajuste os limiares ou amplie o histórico.")

    anos_unicos = sorted(set(anos_amostra))
    indice_corte = max(1, int(len(anos_unicos) * 0.8))
    if indice_corte >= len(anos_unicos):
        raise ValueError("Histórico anual insuficiente para um backtest temporal.")
    ano_teste = anos_unicos[indice_corte]
    treino = [i for i, ano in enumerate(anos_amostra) if ano < ano_teste - horizonte]
    teste = [i for i, ano in enumerate(anos_amostra) if ano >= ano_teste]
    if len(treino) < 20 or len(teste) < 5:
        raise ValueError("Dados insuficientes antes/depois do corte temporal para validar o modelo.")
    if len({linhas_y[i] for i in treino}) < 2 or len({linhas_y[i] for i in teste}) < 2:
        raise ValueError("O backtest não contém as duas classes (com e sem impacto) no treino e no teste.")

    _reportar_progresso(
        progresso,
        62,
        f"Backtest temporal: treino antes de {ano_teste - horizonte}; teste desde {ano_teste}; "
        f"{len(treino)} amostras de treino e {len(teste)} de teste.",
    )

    def criar_modelo():
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=2000, random_state=42),
        )

    modelo_teste = criar_modelo()
    rotulos_treino = [linhas_y[i] for i in treino]
    rotulos_teste = [linhas_y[i] for i in teste]
    _reportar_progresso(
        progresso,
        65,
        "Ajustando backtest: imputação pela mediana, padronização z-score e regressão logística.",
    )
    modelo_teste.fit([linhas_x[i] for i in treino], rotulos_treino)
    _reportar_progresso(progresso, 70, "Calculando probabilidades do teste e métricas de Brier.")
    probabilidades_teste = modelo_teste.predict_proba([linhas_x[i] for i in teste])[:, 1]
    brier = float(brier_score_loss(rotulos_teste, probabilidades_teste))
    probabilidade_base = sum(rotulos_treino) / len(rotulos_treino)
    brier_base = float(brier_score_loss(rotulos_teste, [probabilidade_base] * len(rotulos_teste)))
    habilidade_brier = 1 - brier / brier_base if brier_base else 0.0
    _reportar_progresso(
        progresso,
        74,
        f"Brier={brier:.4f}; referência de prevalência={brier_base:.4f}; habilidade={habilidade_brier:.4f}.",
    )

    modelo_final = criar_modelo()
    _reportar_progresso(progresso, 77, "Ajustando o modelo final com todo o histórico elegível.")
    modelo_final.fit(linhas_x, linhas_y)
    _reportar_progresso(
        progresso,
        85,
        "Modelo ajustado: p=1/(1+exp(-eta)); eta=intercepto+soma(beta_j*z_j).",
    )
    previsoes = []
    candidatos = [registro for registro in ultimas if registro[0] in locais_compativeis]
    dados_futuros = [[registro[2].get(variavel, float("nan")) for variavel in variaveis] for registro in candidatos]
    _reportar_progresso(progresso, 88, "Calculando probabilidades para o horizonte selecionado.")
    probabilidades_futuras = modelo_final.predict_proba(dados_futuros)[:, 1]
    ultimo_percentual = -1
    total_candidatos = max(1, len(candidatos))
    for indice, ((local, ano, _), probabilidade) in enumerate(zip(candidatos, probabilidades_futuras), start=1):
        percentual = 89 + (5 * indice // total_candidatos)
        if percentual != ultimo_percentual:
            _reportar_progresso(progresso, percentual, f"Organizando previsões por localidade: {indice}/{len(candidatos)}.")
            ultimo_percentual = percentual
        previsoes.append({
            "local": local,
            "ultimo_ano_observado": ano,
            "horizonte_anos": horizonte,
            "probabilidade_impacto": round(float(probabilidade), 6),
            "limiar_mortes": limite_mortes,
            "limiar_afetados": limite_afetados,
            "limiar_prejuizo_usd": limite_prejuizo_usd,
        })
    previsoes.sort(key=lambda item: item["probabilidade_impacto"], reverse=True)

    classificador = modelo_final.named_steps["logisticregression"]
    coeficientes = {
        nome: float(coeficiente)
        for nome, coeficiente in zip(nomes_variaveis, classificador.coef_[0])
    }
    resultado = {
        "tema": tema,
        "horizonte_anos": horizonte,
        "observacoes_treino": len(treino),
        "observacoes_teste": len(teste),
        "ano_inicio_teste": ano_teste,
        "brier_score": round(brier, 4),
        "brier_base": round(brier_base, 4),
        "habilidade_brier": round(habilidade_brier, 4),
        "intercepto": float(classificador.intercept_[0]),
        "coeficientes_padronizados": coeficientes,
        "previsoes": previsoes,
        "premissa": "Preditores mantidos nos últimos valores observados; não é uma previsão dos próprios preditores.",
    }
    if pasta_saida:
        _reportar_progresso(progresso, 96, "Exportando probabilidades, limiares e horizonte para CSV.")
        pasta = Path(pasta_saida)
        pasta.mkdir(parents=True, exist_ok=True)
        nome = re.sub(r"[^a-zA-Z0-9]+", "_", tema.lower()).strip("_") or "tema"
        caminho_saida = pasta / f"risco_impacto_{nome}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        campos = list(previsoes[0]) if previsoes else []
        with caminho_saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(previsoes)
        resultado["arquivo_saida"] = str(caminho_saida)
    _reportar_progresso(progresso, 100, "Cruzamento concluído.")
    return resultado
