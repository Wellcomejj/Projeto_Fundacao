import csv
import re
import unicodedata
from pathlib import Path
from collections import Counter
from typing import List

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "from", 
    "is", "are", "was", "were", "be", "been", "using", "based", "study", "analysis", "approach",
    "o", "os", "as", "um", "uma", "e", "ou", "de", "do", "da", "dos", "das", "em", "no", "na",
    "para", "com", "por", "como", "sobre", "entre", "estudo"
}

PADROES_MATEMATICOS = [
    r"\bdifferential equations?\b",
    r"\bstochastic (?:models?|processes?|dynamics?)\b",
    r"\bkinetic (?:models?|equations?|analysis)\b",
    r"\breaction[\s-]diffusion\b",
    r"\bnonlinear (?:dynamics?|systems?)\b",
    r"\bdynamical systems?\b",
    r"\bthermodynamic (?:models?|laws?)\b",
    r"\bnetwork (?:topology|theory|models?)\b",
    r"\bmathematical (?:models?|framework)\b",
    r"\bequacoes? diferenciais?\b",
    r"\bmodelos? estocasticos?\b",
    r"\bdinamica nao linear\b",
    r"\bmodelagem matematica\b",
]

def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return texto.casefold()


def tokenizar(texto: str) -> List[str]:
    return re.findall(r"\b[a-z0-9]+\b", normalizar_texto(texto))


def extrair_palavras_chave(texto: str) -> List[str]:
    return [palavra for palavra in tokenizar(texto) if palavra not in STOPWORDS]

def extrair_bigramas(palavras: List[str]) -> List[str]:
    return [
        f"{palavras[indice]} {palavras[indice + 1]}"
        for indice in range(len(palavras) - 1)
        if palavras[indice] not in STOPWORDS and palavras[indice + 1] not in STOPWORDS
    ]

def extrair_padroes_especificos(titulos: List[str]) -> Counter:
    contagem_padroes = Counter()
    for titulo in titulos:
        titulo_lc = normalizar_texto(titulo)
        for padrao in PADROES_MATEMATICOS:
            for m in re.findall(padrao, titulo_lc):
                contagem_padroes[m] += 1
    return contagem_padroes

def minerar_termos_interdisciplinares():
    pasta_data = Path(__file__).resolve().parent.parent / "Data"
    arquivos = list(pasta_data.glob("artigos_interdisciplinares_*.csv"))
    arquivos.extend(pasta_data.glob("artigos_classificados_*.csv"))
    if not arquivos:
        print(f"Nenhum arquivo de dados encontrado em {pasta_data} para mineracao.")
        return
    arquivo_alvo = max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime)

    print(f"Lendo e minerando termos do arquivo: {arquivo_alvo}\n")

    textos = []
    with open(arquivo_alvo, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            texto = " ".join(filter(None, [row.get("titulo", ""), row.get("resumo", "")]))
            if texto.strip():
                textos.append(texto)

    if not textos:
        print("Nenhum titulo ou resumo encontrado para analise.")
        return

    todas_palavras = []
    todos_bigramas = []
    for texto in textos:
        palavras_originais = tokenizar(texto)
        todas_palavras.extend(palavra for palavra in palavras_originais if palavra not in STOPWORDS)
        todos_bigramas.extend(extrair_bigramas(palavras_originais))

    contagem_palavras = Counter(todas_palavras)
    contagem_bigramas = Counter(todos_bigramas)
    contagem_padroes = extrair_padroes_especificos(textos)
    linhas_relatorio = []
    for tipo, contagem in (
        ("padrao", contagem_padroes),
        ("bigrama", contagem_bigramas),
        ("termo", contagem_palavras),
    ):
        linhas_relatorio.extend({
            "tipo": tipo,
            "termo": termo,
            "ocorrencias": quantidade,
            "documentos_analisados": len(textos),
            "media_ocorrencias_por_documento": round(quantidade / len(textos), 6),
        } for termo, quantidade in contagem.items())
    caminho_relatorio = pasta_data / f"analise_termos_{arquivo_alvo.stem}.csv"
    with open(caminho_relatorio, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tipo", "termo", "ocorrencias", "documentos_analisados", "media_ocorrencias_por_documento"],
        )
        writer.writeheader()
        writer.writerows(linhas_relatorio)

    print("=" * 70)
    print("MINERACAO DE TERMOS E CONCEITOS MATEMATICOS")
    print("=" * 70)
    print(f"Total de titulos e resumos analisados: {len(textos)}\n")

    print("1. Padroes especificos encontrados:")
    for padrao, qtd in contagem_padroes.most_common(10):
        print(f"   - [{qtd}x] {padrao.title()}")

    print("\n2. Bigramas:")
    for term, qtd in contagem_bigramas.most_common(10):
        print(f"   - [{qtd}x] {term}")

    print("\n3. Termos individuais mais frequentes:")
    for term, qtd in contagem_palavras.most_common(10):
        print(f"   - [{qtd}x] {term}")
    print(f"\nRelatorio estruturado: {caminho_relatorio}")
    print("=" * 70)