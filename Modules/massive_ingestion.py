import asyncio
import aiohttp
import csv
import html
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

HEADERS = {
    "User-Agent": "ProjetoFundacao/1.0 (mailto:victor.araujo.arantes@protonmail.com)"
}

STOPWORDS_BUSCA = {
    "the", "and", "for", "with", "from", "that", "this", "into", "using",
    "como", "para", "com", "entre", "sobre", "uma", "um", "dos", "das",
    "de", "da", "do", "e", "ao", "aos", "a", "o", "as", "os", "em", "no", "na",
}
TRADUCOES_CIENTIFICAS = {
    "astrobiologia": "astrobiology", "biologia": "biology", "biologico": "biological",
    "brasil": "brazil", "brasileiro": "brazilian", "brasileira": "brazilian",
    "celula": "cell", "dinamica": "dynamics", "equacao": "equation",
    "equacoes": "equations", "evolucao": "evolution", "fisica": "physics",
    "fisico": "physical", "matematica": "mathematics", "matematico": "mathematical",
    "matematicos": "mathematical", "modelo": "model", "modelos": "models",
    "origem": "origin", "quimica": "chemistry", "quimico": "chemical",
    "simulacao": "simulation", "sistema": "system", "sistemas": "systems",
    "termodinamica": "thermodynamics", "terremoto": "earthquake", "japao": "japan",
    "terremotos": "earthquakes", "vidas": "life", "vida": "life",
    "estocastico": "stochastic", "estocasticos": "stochastic",
}


def normalizar_doi(doi: str) -> str:
    doi_limpo = (doi or "").strip().lower()
    doi_limpo = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi_limpo)
    doi_limpo = re.sub(r"^doi:\s*", "", doi_limpo)
    return doi_limpo.rstrip(".,;)")


def limpar_texto(texto: str) -> str:
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))
    return re.sub(r"\s+", " ", texto).strip()


def reconstruir_resumo_openalex(indice: Dict[str, List[int]]) -> str:
    if not indice:
        return ""
    palavras = [""] * (max(posicao for posicoes in indice.values() for posicao in posicoes) + 1)
    for palavra, posicoes in indice.items():
        for posicao in posicoes:
            palavras[posicao] = palavra
    return " ".join(palavra for palavra in palavras if palavra)


def expandir_termo_busca(termo: str) -> List[str]:
    texto_normalizado = unicodedata.normalize("NFKD", termo.casefold())
    texto_normalizado = "".join(caractere for caractere in texto_normalizado
                                if not unicodedata.combining(caractere))
    palavras = re.findall(r"[a-z0-9]+", texto_normalizado)
    palavras_ingles = [TRADUCOES_CIENTIFICAS.get(palavra, palavra) for palavra in palavras]
    traduzido = " ".join(palavra for palavra in palavras_ingles if palavra not in STOPWORDS_BUSCA)
    variantes = [termo.strip()]
    if traduzido and traduzido.casefold() != termo.strip().casefold():
        variantes.append(traduzido)
    return list(dict.fromkeys(variantes))


def texto_comparavel(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").casefold())
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", texto).strip()


def corresponde_ao_filtro(termo: str, titulo: str, resumo: str, modo_busca: str = "todos") -> bool:
    if modo_busca == "frase":
        frase = texto_comparavel(termo)
        return bool(frase) and (
            frase in texto_comparavel(titulo) or frase in texto_comparavel(resumo)
        )

    conteudo = texto_comparavel(f"{titulo} {resumo}")
    palavras = {
        palavra for palavra in re.findall(r"[a-z0-9]+", texto_comparavel(termo))
        if len(palavra) > 2 and palavra not in STOPWORDS_BUSCA
    }
    palavras_conteudo = set(re.findall(r"[a-z0-9]+", conteudo))
    return bool(palavras) and palavras.issubset(palavras_conteudo)


def formatar_consulta_api(termo: str, modo_busca: str) -> str:
    if modo_busca == "frase":
        return f'"{termo.strip()}"'
    return termo.strip()


def pontuar_relevancia(termo: str, titulo: str, resumo: str) -> float:
    palavras_titulo = set(re.findall(r"[\w-]+", titulo.lower(), flags=re.UNICODE))
    palavras_resumo = set(re.findall(r"[\w-]+", resumo.lower(), flags=re.UNICODE))
    pontuacoes = []
    for variante in expandir_termo_busca(termo):
        palavras = {
            palavra.lower()
            for palavra in re.findall(r"[\w-]+", variante, flags=re.UNICODE)
            if len(palavra) > 2 and palavra.lower() not in STOPWORDS_BUSCA
        }
        if palavras:
            cobertura_titulo = len(palavras & palavras_titulo) / len(palavras)
            cobertura_resumo = len(palavras & palavras_resumo) / len(palavras)
            pontuacoes.append(2 * cobertura_titulo + cobertura_resumo)
    return round(max(pontuacoes, default=0.0), 3)


def criar_registro(
    titulo: str,
    doi: str,
    ano: Any,
    fonte: str,
    url: str = "",
    resumo: str = "",
    idioma: str = "",
    tipo_publicacao: str = "",
    citacoes: Any = "",
    revista: str = "",
    autores: str = "",
    termo_busca: str = "",
    pdf_url: str = "",
    acesso_aberto: str = "",
) -> Dict[str, Any]:
    titulo = limpar_texto(titulo)
    resumo = limpar_texto(resumo)
    return {
        "titulo": titulo,
        "doi": normalizar_doi(doi),
        "ano": ano,
        "fonte": fonte,
        "fontes": fonte,
        "idioma": idioma or "",
        "tipo_publicacao": tipo_publicacao or "",
        "citacoes": citacoes if citacoes is not None else "",
        "revista": revista or "",
        "autores": autores or "",
        "resumo": resumo,
        "pdf_url": pdf_url or "",
        "acesso_aberto": acesso_aberto or "",
        "url": url or "",
        "termo_pesquisa": termo_busca,
        "relevancia": pontuar_relevancia(termo_busca, titulo, resumo),
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def obter_json(
    session: aiohttp.ClientSession,
    url: str,
    params: Dict[str, Any],
    fonte: str,
    termo_busca: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    try:
        async with session.get(url, params=params, headers=headers or HEADERS, timeout=20) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            detalhe = (await resp.text())[:500]
            print(f"Erro {fonte} ({termo_busca}): HTTP {resp.status}: {detalhe}")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as erro:
        print(f"Erro {fonte} ({termo_busca}): {erro}")
    return {}


async def obter_json_intervalado(
    session: aiohttp.ClientSession,
    url: str,
    params: Dict[str, Any],
    fonte: str,
    termo_busca: str,
    bloqueio: asyncio.Lock,
    intervalo: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    async with bloqueio:
        await asyncio.sleep(intervalo)
        return await obter_json(session, url, params, fonte, termo_busca, headers)


async def obter_texto_intervalado(
    session: aiohttp.ClientSession,
    url: str,
    params: Dict[str, Any],
    fonte: str,
    termo_busca: str,
    bloqueio: asyncio.Lock,
    intervalo: float,
) -> str:
    async with bloqueio:
        await asyncio.sleep(intervalo)
        try:
            async with session.get(url, params=params, headers=HEADERS, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.text()
                print(f"Erro {fonte} ({termo_busca}): HTTP {resp.status}: {(await resp.text())[:400]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as erro:
            print(f"Erro {fonte} ({termo_busca}): {erro}")
    return ""


async def buscar_openalex_paginado(
    session: aiohttp.ClientSession, 
    termo_busca: str, 
    lang_code: str, 
    meta_total: int = 300, 
    ano_inicio: int = 1950, 
    ano_fim: int = 2026,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
) -> List[Dict[str, Any]]:
    artigos = []
    cursor = "*"
    params = {
        "search": formatar_consulta_api(termo_busca, modo_busca),
        "filter": (
            f"publication_year:{ano_inicio}-{ano_fim},type:article"
            + (",open_access.is_oa:true" if somente_acesso_aberto else "")
        ),
        "per-page": min(100, meta_total),
        "select": "id,doi,title,publication_year,type,cited_by_count,language,abstract_inverted_index,primary_location,authorships,open_access,best_oa_location",
    }
    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    
    while len(artigos) < meta_total and cursor:
        params["cursor"] = cursor
        data = await obter_json(
            session,
            "https://api.openalex.org/works",
            params,
            "OpenAlex",
            termo_busca,
        )
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            titulo = item.get("title") or ""
            if not titulo:
                continue
            localizacao = item.get("primary_location") or {}
            revista = (localizacao.get("source") or {}).get("display_name", "")
            autores = "; ".join(
                autoria.get("author", {}).get("display_name", "")
                for autoria in item.get("authorships", [])
                if autoria.get("author", {}).get("display_name")
            )
            resumo = reconstruir_resumo_openalex(item.get("abstract_inverted_index") or {})
            artigos.append(criar_registro(
                titulo=titulo,
                doi=item.get("doi", ""),
                ano=item.get("publication_year"),
                fonte="OpenAlex",
                url=item.get("id", ""),
                resumo=resumo,
                idioma=item.get("language", ""),
                tipo_publicacao=item.get("type", ""),
                citacoes=item.get("cited_by_count", ""),
                revista=revista,
                autores=autores,
                termo_busca=termo_busca,
                pdf_url=(item.get("best_oa_location") or {}).get("pdf_url", ""),
                acesso_aberto="Y" if (item.get("open_access") or {}).get("is_oa") else "N",
            ))
            if len(artigos) >= meta_total:
                break
        cursor = data.get("meta", {}).get("next_cursor")
            
    return artigos


async def buscar_semantic_paginado(
    session: aiohttp.ClientSession, 
    termo_busca: str, 
    lang_code: str, 
    meta_total: int = 200, 
    ano_inicio: int = 1950, 
    ano_fim: int = 2026,
    request_lock: Optional[asyncio.Lock] = None,
    modo_busca: str = "todos",
) -> List[Dict[str, Any]]:
    artigos = []
    offset = 0
    limite = min(meta_total, 100)
    request_lock = request_lock or asyncio.Lock()
    headers = dict(HEADERS)
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    
    while len(artigos) < limite and offset < 1000:
        params = {
            "query": formatar_consulta_api(termo_busca, modo_busca),
            "offset": offset,
            "limit": min(100, limite - len(artigos)),
            "fields": "title,abstract,externalIds,year,url,citationCount,publicationTypes,journal,authors,openAccessPdf",
        }
        data = await obter_json_intervalado(
            session,
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params,
            "Semantic Scholar",
            termo_busca,
            request_lock,
            1.1,
            headers,
        )
        results = data.get("data", [])
        if not results:
            break
        for item in results:
            ano = item.get("year")
            titulo = item.get("title") or ""
            if not titulo or not ano or not ano_inicio <= ano <= ano_fim:
                continue
            tipos = item.get("publicationTypes") or []
            if tipos and not set(tipos).intersection({"JournalArticle", "Review", "Study"}):
                continue
            doi = (item.get("externalIds") or {}).get("DOI", "")
            revista = item.get("journal") or {}
            autores = "; ".join(
                autor.get("name", "")
                for autor in item.get("authors", [])
                if autor.get("name")
            )
            artigos.append(criar_registro(
                titulo=titulo,
                doi=doi,
                ano=ano,
                fonte="Semantic Scholar",
                url=item.get("url", ""),
                resumo=item.get("abstract", ""),
                tipo_publicacao="; ".join(tipos),
                citacoes=item.get("citationCount", ""),
                revista=revista.get("name", ""),
                autores=autores,
                termo_busca=termo_busca,
                pdf_url=(item.get("openAccessPdf") or {}).get("url", ""),
                acesso_aberto="Y" if (item.get("openAccessPdf") or {}).get("url") else "N",
            ))
            if len(artigos) >= meta_total:
                break
        offset += len(results)
        if len(results) < params["limit"]:
            break
            
    return artigos


async def buscar_crossref_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    modo_busca: str = "todos",
) -> List[Dict[str, Any]]:
    artigos = []
    offset = 0
    rows = min(100, meta_total)
    params = {
        "query": formatar_consulta_api(termo_busca, modo_busca),
        "filter": (
            f"from-pub-date:{ano_inicio}-01-01,"
            f"until-pub-date:{ano_fim}-12-31,type:journal-article"
        ),
        "rows": rows,
    }

    while len(artigos) < meta_total and offset < 10000:
        params["offset"] = offset
        data = await obter_json(
            session,
            "https://api.crossref.org/works",
            params,
            "Crossref",
            termo_busca,
        )
        results = data.get("message", {}).get("items", [])
        if not results:
            break
        for item in results:
            titulo = (item.get("title") or [""])[0]
            datas = (
                item.get("published-print", {}).get("date-parts")
                or item.get("published-online", {}).get("date-parts")
                or item.get("issued", {}).get("date-parts")
                or []
            )
            ano = datas[0][0] if datas and datas[0] else None
            titulo_normalizado = re.sub(r"^[\W_]+", "", titulo.lower())
            registro_atualizado = item.get("update-to")
            if (
                not titulo
                or not ano
                or not ano_inicio <= ano <= ano_fim
                or registro_atualizado
                or re.match(r"(?:withdrawal|retraction|retracted|erratum|correction|expression of concern)\b", titulo_normalizado)
            ):
                continue
            autores = "; ".join(
                " ".join(filter(None, [autor.get("given"), autor.get("family")]))
                for autor in item.get("author", [])
                if autor.get("given") or autor.get("family")
            )
            artigos.append(criar_registro(
                titulo=titulo,
                doi=item.get("DOI", ""),
                ano=ano,
                fonte="Crossref",
                url=item.get("URL", ""),
                resumo=item.get("abstract", ""),
                idioma=item.get("language", ""),
                tipo_publicacao=item.get("type", "journal-article"),
                revista=(item.get("container-title") or [""])[0],
                autores=autores,
                termo_busca=termo_busca,
            ))
            if len(artigos) >= meta_total:
                break
        offset += len(results)
        if len(results) < rows:
            break
    return artigos


async def buscar_europe_pmc_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
    request_lock: Optional[asyncio.Lock] = None,
) -> List[Dict[str, Any]]:
    artigos = []
    cursor = "*"
    if modo_busca == "frase":
        consulta_texto = f'TITLE_ABS:"{termo_busca.replace(chr(34), "")}"'
    else:
        palavras = [
            palavra for palavra in re.findall(r"[a-zA-Z0-9]+", texto_comparavel(termo_busca))
            if len(palavra) > 2 and palavra not in STOPWORDS_BUSCA
        ]
        consulta_texto = " AND ".join(f'TITLE_ABS:"{palavra}"' for palavra in palavras)
    params = {
        "query": (
            f"{consulta_texto} AND FIRST_PDATE:[{ano_inicio}-01-01 TO {ano_fim}-12-31]"
            + (" AND OPEN_ACCESS:Y" if somente_acesso_aberto else "")
        ),
        "format": "json",
        "resultType": "core",
        "pageSize": min(100, meta_total),
        "cursorMark": cursor,
    }
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    while len(artigos) < meta_total and cursor:
        params["cursorMark"] = cursor
        data = await obter_json(session, url, params, "Europe PMC", termo_busca)
        results = data.get("resultList", {}).get("result", [])
        if not results:
            break
        for item in results:
            titulo = item.get("title", "")
            ano = item.get("pubYear")
            try:
                ano = int(ano)
            except (TypeError, ValueError):
                continue
            if not titulo or not ano_inicio <= ano <= ano_fim:
                continue
            tipos = (item.get("pubTypeList") or {}).get("pubType", [])
            if isinstance(tipos, str):
                tipos = [tipos]
            full_text_urls = (item.get("fullTextUrlList") or {}).get("fullTextUrl", [])
            pdf_url = next((link.get("url", "") for link in full_text_urls
                            if "pdf" in link.get("documentStyle", "").lower()), "")
            artigo_url = (
                f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id', '')}"
            )
            artigos.append(criar_registro(
                titulo=titulo,
                doi=item.get("doi", ""),
                ano=ano,
                fonte="Europe PMC",
                url=artigo_url,
                resumo=item.get("abstractText", ""),
                idioma=item.get("language", ""),
                tipo_publicacao="; ".join(tipos),
                citacoes=item.get("citedByCount", ""),
                revista=(item.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                autores=item.get("authorString", ""),
                termo_busca=termo_busca,
                pdf_url=pdf_url,
                acesso_aberto=item.get("isOpenAccess", ""),
            ))
            if len(artigos) >= meta_total:
                break
        novo_cursor = data.get("nextCursorMark")
        if not novo_cursor or novo_cursor == cursor:
            break
        cursor = novo_cursor
    return artigos


async def buscar_datacite_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
    request_lock: Optional[asyncio.Lock] = None,
) -> List[Dict[str, Any]]:
    artigos = []
    bloqueio = request_lock or asyncio.Lock()
    tipos_artigo = ("JournalArticle", "Preprint", "Thesis", "ConferencePaper")
    por_tipo = max(1, (meta_total + len(tipos_artigo) - 1) // len(tipos_artigo))

    for tipo in tipos_artigo:
        pagina = 1
        coletados_tipo = 0
        consulta = formatar_consulta_api(termo_busca, modo_busca)
        params = {
            "query": f"{consulta} AND types.resourceTypeGeneral:{tipo}",
            "page[size]": min(100, por_tipo),
        }
        while coletados_tipo < por_tipo and pagina <= 100:
            params["page[number]"] = pagina
            data = await obter_json_intervalado(
                session,
                "https://api.datacite.org/dois",
                params,
                "DataCite",
                termo_busca,
                bloqueio,
                0.15,
            )
            results = data.get("data", [])
            if not results:
                break
            for item in results:
                atributos = item.get("attributes") or {}
                tipos = atributos.get("types") or {}
                tipo_registro = tipos.get("resourceTypeGeneral", "")
                if tipo_registro != tipo:
                    continue
                ano = atributos.get("publicationYear")
                if not ano or not ano_inicio <= int(ano) <= ano_fim:
                    continue
                titulos = atributos.get("titles") or []
                titulo = next((registro.get("title", "") for registro in titulos if registro.get("title")), "")
                descricoes = atributos.get("descriptions") or []
                resumo = next((registro.get("description", "") for registro in descricoes
                               if registro.get("descriptionType", "").casefold() == "abstract"), "")
                criadores = atributos.get("creators") or []
                autores = "; ".join(
                    criador.get("name", "") for criador in criadores if criador.get("name")
                )
                direitos = atributos.get("rightsList") or []
                licencas_abertas = any(
                    any(marcador in (direito.get("rightsUri") or direito.get("rights", "")).lower()
                        for marcador in ("creativecommons.org", "publicdomain", "open access"))
                    for direito in direitos
                )
                content_url = atributos.get("contentUrl") or ""
                acesso_aberto = "Y" if licencas_abertas else ""
                if somente_acesso_aberto and not acesso_aberto:
                    continue
                artigos.append(criar_registro(
                    titulo=titulo,
                    doi=atributos.get("doi", ""),
                    ano=int(ano),
                    fonte="DataCite",
                    url=atributos.get("url", ""),
                    resumo=resumo,
                    idioma=atributos.get("language", ""),
                    tipo_publicacao=tipo_registro,
                    revista=atributos.get("publisher", ""),
                    autores=autores,
                    termo_busca=termo_busca,
                    pdf_url=content_url if content_url.lower().endswith(".pdf") else "",
                    acesso_aberto=acesso_aberto,
                ))
                coletados_tipo += 1
                if coletados_tipo >= por_tipo:
                    break
            if len(results) < params["page[size]"]:
                break
            pagina += 1
    return artigos[:meta_total]


async def buscar_openaire_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
    request_lock: Optional[asyncio.Lock] = None,
) -> List[Dict[str, Any]]:
    artigos = []
    palavras = [
        palavra for palavra in re.findall(r"[a-zA-Z0-9]+", texto_comparavel(termo_busca))
        if len(palavra) > 2 and palavra not in STOPWORDS_BUSCA
    ]
    if modo_busca == "frase":
        consulta = f'"{termo_busca.strip()}"'
    else:
        consulta = " AND ".join(f'"{palavra}"' for palavra in palavras) or f'"{termo_busca}"'
    params = {
        "search": consulta,
        "type": "publication",
        "fromPublicationYear": ano_inicio,
        "toPublicationYear": ano_fim,
        "pageSize": min(100, meta_total),
        "sortBy": "relevance DESC",
    }
    if somente_acesso_aberto:
        params["accessRightLabel"] = '"Open Access"'
    bloqueio = request_lock or asyncio.Lock()

    pagina = 1
    while len(artigos) < meta_total and pagina <= 100:
        params["page"] = pagina
        data = await obter_json_intervalado(
            session,
            "https://api.openaire.eu/graph/v3/research-products",
            params,
            "OpenAIRE",
            termo_busca,
            bloqueio,
            0.15,
        )
        resultados = data.get("results", [])
        if not resultados:
            break
        for item in resultados:
            titulo = item.get("mainTitle") or ""
            data_publicacao = item.get("publicationDate") or ""
            try:
                ano = int(data_publicacao[:4])
            except (TypeError, ValueError):
                continue
            if not titulo or not ano_inicio <= ano <= ano_fim:
                continue
            instancias = item.get("instances") or []
            direitos = item.get("bestAccessRight") or {}
            acesso_aberto = str(direitos.get("label", "")).casefold() in {"open", "open access"}
            if not acesso_aberto:
                acesso_aberto = any(
                    str((instancia.get("accessRight") or {}).get("label", "")).casefold()
                    in {"open", "open access"}
                    for instancia in instancias
                )
            if somente_acesso_aberto and not acesso_aberto:
                continue
            pids = item.get("pids") or []
            doi = next((pid.get("value", "") for pid in pids if pid.get("scheme", "").casefold() == "doi"), "")
            urls = [url for instancia in instancias for url in instancia.get("urls", []) if url]
            pdf_url = next((url for url in urls if url.lower().split("?")[0].endswith(".pdf")), "")
            resumo = " ".join(
                descricao.get("value", "") if isinstance(descricao, dict) else str(descricao)
                for descricao in (item.get("descriptions") or [])
            )
            autores = "; ".join(
                autor.get("fullName", "") for autor in (item.get("authors") or [])
                if autor.get("fullName")
            )
            artigo_url = next((url for url in urls if "doi.org/" in url), "") or (f"https://doi.org/{doi}" if doi else "")
            artigos.append(criar_registro(
                titulo=titulo,
                doi=doi,
                ano=ano,
                fonte="OpenAIRE",
                url=artigo_url,
                resumo=resumo,
                idioma=(item.get("language") or {}).get("label", ""),
                tipo_publicacao=item.get("type", "publication"),
                revista=(item.get("container") or {}).get("name", ""),
                autores=autores,
                termo_busca=termo_busca,
                pdf_url=pdf_url,
                acesso_aberto="Y" if acesso_aberto else "N",
            ))
            if len(artigos) >= meta_total:
                break
        if len(resultados) < params["pageSize"]:
            break
        pagina += 1
    return artigos


async def buscar_pubmed_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
    request_lock: Optional[asyncio.Lock] = None,
) -> List[Dict[str, Any]]:
    bloqueio = request_lock or asyncio.Lock()
    palavras = [
        palavra for palavra in re.findall(r"[a-zA-Z0-9]+", texto_comparavel(termo_busca))
        if len(palavra) > 2 and palavra not in STOPWORDS_BUSCA
    ]
    if modo_busca == "frase":
        consulta = f'"{termo_busca.replace(chr(34), "")}"[Title/Abstract]'
    else:
        consulta = " AND ".join(f'"{palavra}"[Title/Abstract]' for palavra in palavras)
    consulta += f" AND {ano_inicio}:{ano_fim}[dp]"
    if somente_acesso_aberto:
        consulta += " AND free full text[sb]"

    parametros = {
        "db": "pubmed",
        "term": consulta,
        "retmode": "json",
        "retmax": min(meta_total, 500),
        "tool": "ProjetoFundacao",
        "email": "victor.araujo.arantes@protonmail.com",
    }
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        parametros["api_key"] = api_key
    resposta_busca = await obter_json_intervalado(
        session,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        parametros,
        "PubMed",
        termo_busca,
        bloqueio,
        0.36,
    )
    ids = resposta_busca.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    xml = await obter_texto_intervalado(
        session,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
        "PubMed",
        termo_busca,
        bloqueio,
        0.36,
    )
    if not xml:
        return []
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as erro:
        print(f"Erro ao interpretar resposta PubMed ({termo_busca}): {erro}")
        return []

    artigos = []
    for registro in raiz.findall(".//PubmedArticle"):
        artigo = registro.find(".//Article")
        if artigo is None:
            continue
        titulo = limpar_texto("".join(artigo.find("ArticleTitle").itertext())) if artigo.find("ArticleTitle") is not None else ""
        resumo = " ".join(
            limpar_texto("".join(bloco.itertext()))
            for bloco in artigo.findall(".//Abstract/AbstractText")
        )
        data_ano = artigo.findtext(".//JournalIssue/PubDate/Year") or artigo.findtext(".//ArticleDate/Year") or ""
        if not data_ano:
            medline_date = artigo.findtext(".//JournalIssue/PubDate/MedlineDate") or ""
            data_ano = re.search(r"\b(?:18|19|20)\d{2}\b", medline_date).group(0) if re.search(r"\b(?:18|19|20)\d{2}\b", medline_date) else ""
        try:
            ano = int(data_ano)
        except (TypeError, ValueError):
            continue
        if not titulo or not ano_inicio <= ano <= ano_fim:
            continue
        identificadores = registro.findall(".//PubmedData/ArticleIdList/ArticleId")
        doi = next((id_element.text or "" for id_element in identificadores
                    if id_element.get("IdType") == "doi"), "")
        pmc = next((id_element.text or "" for id_element in identificadores
                    if id_element.get("IdType") == "pmc"), "")
        autores = "; ".join(
            " ".join(filter(None, [autor.findtext("ForeName"), autor.findtext("LastName")]))
            for autor in artigo.findall(".//AuthorList/Author")
            if autor.findtext("ForeName") or autor.findtext("LastName")
        )
        tipos = [item.text or "" for item in artigo.findall(".//PublicationTypeList/PublicationType")]
        artigo_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/" if pmc else f"https://pubmed.ncbi.nlm.nih.gov/{registro.findtext('.//PMID')}/"
        artigos.append(criar_registro(
            titulo=titulo,
            doi=doi,
            ano=ano,
            fonte="PubMed",
            url=artigo_url,
            resumo=resumo,
            idioma="; ".join(item.get("Language", "") for item in artigo.findall("Language")),
            tipo_publicacao="; ".join(tipos),
            revista=artigo.findtext(".//Journal/Title", default=""),
            autores=autores,
            termo_busca=termo_busca,
            acesso_aberto="Y" if somente_acesso_aberto else "",
        ))
    return artigos


async def buscar_arxiv_paginado(
    session: aiohttp.ClientSession,
    termo_busca: str,
    ano_inicio: int,
    ano_fim: int,
    meta_total: int,
    request_lock: Optional[asyncio.Lock] = None,
    modo_busca: str = "todos",
) -> List[Dict[str, Any]]:
    artigos = []
    limite = min(meta_total, 500)
    inicio = 0
    tamanho_pagina = min(100, limite)
    termo_arxiv = re.sub(r'["{}]', " ", termo_busca).strip()
    palavras_arxiv = [
        palavra for palavra in re.findall(r"[a-zA-Z0-9]+", texto_comparavel(termo_arxiv))
        if len(palavra) > 2 and palavra not in STOPWORDS_BUSCA
    ]
    if modo_busca == "frase":
        consulta_arxiv = f'all:"{termo_arxiv}"'
    else:
        consulta_arxiv = " AND ".join(f'all:"{palavra}"' for palavra in palavras_arxiv)
        if not consulta_arxiv:
            consulta_arxiv = f'all:"{termo_arxiv}"'
    params = {
        "search_query": consulta_arxiv,
        "sortBy": "relevance",
        "sortOrder": "descending",
        "max_results": tamanho_pagina,
    }
    request_lock = request_lock or asyncio.Lock()
    namespaces = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    while len(artigos) < limite:
        params["start"] = inicio
        try:
            async with request_lock:
                await asyncio.sleep(3.1)
                async with session.get(
                    "https://export.arxiv.org/api/query",
                    params=params,
                    headers=HEADERS,
                    timeout=30,
                ) as resp:
                    if resp.status != 200:
                        detalhe = (await resp.text())[:400]
                        print(f"Erro arXiv ({termo_busca}): HTTP {resp.status}: {detalhe}")
                        break
                    raiz = ET.fromstring(await resp.text())
        except (aiohttp.ClientError, asyncio.TimeoutError, ET.ParseError) as erro:
            print(f"Erro arXiv ({termo_busca}): {erro}")
            break

        entradas = raiz.findall("atom:entry", namespaces)
        if not entradas:
            break
        for entrada in entradas:
            titulo = entrada.findtext("atom:title", default="", namespaces=namespaces)
            resumo = entrada.findtext("atom:summary", default="", namespaces=namespaces)
            data_publicacao = entrada.findtext("atom:published", default="", namespaces=namespaces)
            try:
                ano = int(data_publicacao[:4])
            except (TypeError, ValueError):
                continue
            if not titulo or not ano_inicio <= ano <= ano_fim:
                continue
            artigo_url = entrada.findtext("atom:id", default="", namespaces=namespaces)
            pdf_url = next((link.get("href", "") for link in entrada.findall("atom:link", namespaces)
                            if link.get("title") == "pdf"), "")
            autores = "; ".join(
                autor.findtext("atom:name", default="", namespaces=namespaces)
                for autor in entrada.findall("atom:author", namespaces)
            )
            revista = entrada.findtext("arxiv:journal_ref", default="", namespaces=namespaces)
            doi = entrada.findtext("arxiv:doi", default="", namespaces=namespaces)
            categorias = "; ".join(
                categoria.get("term", "")
                for categoria in entrada.findall("atom:category", namespaces)
                if categoria.get("term")
            )
            artigos.append(criar_registro(
                titulo=titulo,
                doi=doi,
                ano=ano,
                fonte="arXiv",
                url=artigo_url,
                resumo=resumo,
                tipo_publicacao="preprint" + ("; publicado" if revista else ""),
                revista=revista or categorias,
                autores=autores,
                termo_busca=termo_busca,
                pdf_url=pdf_url,
                acesso_aberto="Y",
            ))
            if len(artigos) >= limite:
                break
        inicio += len(entradas)
        if len(entradas) < tamanho_pagina:
            break
    return artigos


async def executar_busca_artigos(
    termo_usuario: str,
    meta_total_artigos: int = 1500,
    faixas_temporais: List[tuple] = None,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
) -> List[Dict[str, Any]]:
    termo_usuario = termo_usuario.strip()
    if not termo_usuario:
        raise ValueError("O termo de pesquisa não pode ficar vazio.")
    if meta_total_artigos < 1:
        raise ValueError("A meta de artigos deve ser maior que zero.")
    if modo_busca not in {"todos", "frase"}:
        raise ValueError("O modo de busca deve ser 'todos' ou 'frase'.")

    if faixas_temporais is None:
        faixas_temporais = [(1950, datetime.now().year)]
    if not faixas_temporais or any(
        ano_inicio < 1 or ano_fim < ano_inicio for ano_inicio, ano_fim in faixas_temporais
    ):
        raise ValueError("Informe intervalos de anos válidos para a pesquisa.")

    tarefas = []
    limite_por_faixa = max(
        1,
        min(150, (meta_total_artigos * 3 + len(faixas_temporais) - 1) // len(faixas_temporais)),
    )
    variantes_busca = [termo_usuario] if modo_busca == "frase" else expandir_termo_busca(termo_usuario)
    limite_por_consulta = max(1, (limite_por_faixa + len(variantes_busca) - 1) // len(variantes_busca))
    bloqueio_semantic = asyncio.Lock()
    bloqueio_arxiv = asyncio.Lock()
    bloqueio_pubmed = asyncio.Lock()
    bloqueio_datacite = asyncio.Lock()
    bloqueio_openaire = asyncio.Lock()
    openalex_habilitado = bool(os.getenv("OPENALEX_API_KEY"))
    semantic_habilitado = bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))
    fontes_ativas = ["Crossref", "Europe PMC", "arXiv", "DataCite", "OpenAIRE", "PubMed"]
    if openalex_habilitado:
        fontes_ativas.append("OpenAlex")
    if semantic_habilitado:
        fontes_ativas.append("Semantic Scholar")

    if not somente_acesso_aberto:
        print("Fontes publicas sem chave: Crossref, Europe PMC, arXiv, DataCite, OpenAIRE e PubMed.")
    else:
        print("Busca restrita a registros identificados como acesso aberto/texto completo livre.")
    fontes_opcionais = []
    if not openalex_habilitado:
        fontes_opcionais.append("OpenAlex")
    if not semantic_habilitado:
        fontes_opcionais.append("Semantic Scholar")
    if fontes_opcionais:
        print(f"Fontes gratuitas opcionais ignoradas sem chave configurada: {', '.join(fontes_opcionais)}.")

    async with aiohttp.ClientSession() as session:
        for ano_i, ano_f in faixas_temporais:
            for variante in variantes_busca:
                if not somente_acesso_aberto:
                    tarefas.append(buscar_crossref_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta, modo_busca
                    ))
                if openalex_habilitado:
                    tarefas.append(buscar_openalex_paginado(
                        session, variante, "", limite_por_consulta, ano_i, ano_f,
                        modo_busca, somente_acesso_aberto,
                    ))
                if semantic_habilitado:
                    tarefas.append(buscar_semantic_paginado(
                        session, variante, "", limite_por_consulta, ano_i, ano_f,
                        bloqueio_semantic, modo_busca,
                    ))
                tarefas.extend([
                    buscar_europe_pmc_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta,
                        modo_busca, somente_acesso_aberto,
                    ),
                    buscar_datacite_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta,
                        modo_busca, somente_acesso_aberto, bloqueio_datacite,
                    ),
                    buscar_openaire_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta,
                        modo_busca, somente_acesso_aberto, bloqueio_openaire,
                    ),
                    buscar_pubmed_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta,
                        modo_busca, somente_acesso_aberto, bloqueio_pubmed,
                    ),
                ])
                if modo_busca == "frase" or variante == variantes_busca[-1]:
                    tarefas.append(buscar_arxiv_paginado(
                        session, variante, ano_i, ano_f, limite_por_consulta,
                        bloqueio_arxiv, modo_busca,
                    ))

        semaforo = asyncio.Semaphore(6)

        async def limitar_concorrencia(corrotina):
            async with semaforo:
                nome_funcao = corrotina.cr_code.co_name
                fonte = {
                    "buscar_crossref_paginado": "Crossref",
                    "buscar_europe_pmc_paginado": "Europe PMC",
                    "buscar_arxiv_paginado": "arXiv",
                    "buscar_datacite_paginado": "DataCite",
                    "buscar_openaire_paginado": "OpenAIRE",
                    "buscar_pubmed_paginado": "PubMed",
                    "buscar_openalex_paginado": "OpenAlex",
                    "buscar_semantic_paginado": "Semantic Scholar",
                }.get(nome_funcao, nome_funcao)
                try:
                    resultado = await corrotina
                except Exception as erro:
                    print(f"{fonte}: consulta falhou ({erro}).")
                    return []
                print(f"{fonte}: consulta concluida ({len(resultado)} registros).")
                return resultado

        resultados_brutos = []
        tarefas_execucao = [limitar_concorrencia(tarefa) for tarefa in tarefas]
        for tarefa_concluida in asyncio.as_completed(tarefas_execucao):
            resultados_brutos.append(await tarefa_concluida)

    artigos_por_fonte: Dict[str, List[Dict[str, Any]]] = {
        "Crossref": [],
        "OpenAlex": [],
        "Semantic Scholar": [],
        "Europe PMC": [],
        "arXiv": [],
        "DataCite": [],
        "OpenAIRE": [],
        "PubMed": [],
    }
    totais_por_fonte: Dict[str, int] = {fonte: 0 for fonte in artigos_por_fonte}
    for res in resultados_brutos:
        if isinstance(res, Exception):
            print(f"Erro inesperado durante a ingestao: {res}")
            continue
        if isinstance(res, list):
            if res:
                fonte = res[0].get("fonte", "Desconhecida")
                artigos_por_fonte.setdefault(fonte, []).extend(res)
                totais_por_fonte[fonte] = totais_por_fonte.get(fonte, 0) + len(res)

    artigos_unicos: Dict[str, Dict[str, Any]] = {}
    listas_fontes = list(artigos_por_fonte.values())
    maior_lista = max((len(lista) for lista in listas_fontes), default=0)
    for indice in range(maior_lista):
        for lista in listas_fontes:
            if indice >= len(lista):
                continue
            art = lista[indice]
            doi = normalizar_doi(art.get("doi", ""))
            titulo_limpo = re.sub(r"[\W_]+", "", art.get("titulo", "").strip().lower())
            chave = doi or titulo_limpo
            variante_resultado = art.get("termo_pesquisa", termo_usuario)
            if (
                not chave
                or art.get("relevancia", 0) <= 0
                or not corresponde_ao_filtro(variante_resultado, art.get("titulo", ""), art.get("resumo", ""), modo_busca)
                or (somente_acesso_aberto and art.get("acesso_aberto") != "Y")
            ):
                continue
            art["doi"] = doi
            art["variante_consulta"] = variante_resultado
            art["variantes_consulta"] = art["variante_consulta"]
            art["termo_pesquisa"] = termo_usuario
            art["modo_busca"] = modo_busca
            existente = artigos_unicos.get(chave)
            if existente is None:
                artigos_unicos[chave] = art
                continue
            fontes = set(filter(None, existente.get("fontes", "").split("; ")))
            fontes.update(filter(None, art.get("fontes", "").split("; ")))
            existente["fontes"] = "; ".join(sorted(fontes))
            variantes = set(filter(None, existente.get("variantes_consulta", "").split("; ")))
            variantes.add(art["variante_consulta"])
            existente["variantes_consulta"] = "; ".join(sorted(variantes))
            existente["relevancia"] = max(existente.get("relevancia", 0), art.get("relevancia", 0))
            if art.get("acesso_aberto") == "Y":
                existente["acesso_aberto"] = "Y"
            for campo, valor in art.items():
                if not existente.get(campo) and valor:
                    existente[campo] = valor

    artigos_ordenados = sorted(
        artigos_unicos.values(),
        key=lambda artigo: (
            artigo.get("relevancia", 0),
            artigo.get("ano") or 0,
            int(artigo.get("citacoes") or 0) if str(artigo.get("citacoes") or "").isdigit() else 0,
        ),
        reverse=True,
    )
    artigos_finais = artigos_ordenados[:meta_total_artigos]
    for fonte, total in sorted(totais_por_fonte.items()):
        print(f"{fonte}: {total} registros recebidos antes da deduplicação.")
    print(f"Ingestão concluída: {len(artigos_finais)} artigos únicos recuperados.")
    if not artigos_finais:
        print("Nenhum resultado foi obtido. Verifique o termo, o intervalo de anos e os erros HTTP acima.")
    return artigos_finais


async def executar_ingestao_multilingue(
    termo_usuario: str,
    meta_total_artigos: int = 1500,
    faixas_temporais: List[tuple] = None,
    modo_busca: str = "todos",
    somente_acesso_aberto: bool = False,
) -> List[Dict[str, Any]]:
    return await executar_busca_artigos(
        termo_usuario, meta_total_artigos, faixas_temporais, modo_busca, somente_acesso_aberto
    )


def exportar_para_csv(artigos: list, caminho_arquivo: str = None, termo_pesquisa: str = "busca") -> str:
    if not artigos:
        print("Nenhum artigo para exportar.")
        return ""

    if not caminho_arquivo or not caminho_arquivo.endswith(".csv"):
        diretorio_raiz = Path(__file__).resolve().parent.parent
        pasta_data = diretorio_raiz / "Data"
        pasta_data.mkdir(parents=True, exist_ok=True)
        
        termo_slug = "".join([c if c.isalnum() else "_" for c in termo_pesquisa.lower()]).strip("_") or "busca"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho_arquivo = str(pasta_data / f"artigos_{termo_slug}_{timestamp}.csv")

    campos = [
        "titulo", "resumo", "autores", "revista", "doi", "ano", "fonte",
        "fontes", "idioma", "tipo_publicacao", "citacoes", "relevancia",
        "acesso_aberto", "pdf_url", "url", "termo_pesquisa", "variante_consulta",
        "variantes_consulta", "modo_busca", "coletado_em",
    ]

    try:
        with open(caminho_arquivo, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            writer.writeheader()
            for artigo in artigos:
                writer.writerow(artigo)
                
        print(f"Sucesso: {len(artigos)} artigos exportados para: {caminho_arquivo}")
        return caminho_arquivo
    except Exception as e:
        print(f"Erro ao exportar CSV: {e}")
        return ""