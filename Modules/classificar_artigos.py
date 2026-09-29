import csv
import re
import unicodedata
from pathlib import Path
from collections import Counter

TERMOS_CATEGORIAS = {
    "Matemática & Modelagem": [
        "mathemat", "model", "equation", "simulation", "algorithm", "differential",
        "dynamic", "stochastic", "network", "statistic", "probabil", "matem",
        "modelo", "equac", "simul", "algorit", "diferencial", "dinam", "rede",
        "estatistic", "probabil"
    ],
    "Física & Astrofísica": [
        "physics", "physical", "astrophys", "astronom", "cosmolog", "quantum",
        "relativ", "gravit", "particle", "fisic", "astrofis", "astronom", "cosmolog",
        "quant", "relativ", "gravit", "particul"
    ],
    "Química & Termodinâmica": [
        "chemical", "chemistry", "reaction", "thermodynamic", "molecular", "kinetic",
        "catalyst", "prebiotic", "synthesis", "element", "quimic", "reac", "termodinam",
        "cinetic", "catalis", "prebiotic", "sintes", "element"
    ],
    "Biologia & Evolução": [
        "biology", "biological", "evolution", "astrobiology", "cell", "organism",
        "genome", "biolog", "evolu", "origem da vida", "astrobiolog", "celul",
        "organism", "rna", "dna", "genom"
    ]
}

def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", texto.casefold()).strip()


def classificar_artigo(titulo: str, resumo: str = "") -> dict:
    texto = f" {normalizar_texto(titulo)} {normalizar_texto(resumo)} "
    palavras = set(re.findall(r"[a-z0-9]+", texto))
    categorias_encontradas = []
    termos_encontrados = []
    for cat_nome, termos in TERMOS_CATEGORIAS.items():
        termos_categoria = []
        for termo in termos:
            termo_normalizado = normalizar_texto(termo)
            if " " in termo_normalizado:
                encontrado = f" {termo_normalizado} " in texto
            else:
                encontrado = any(
                    palavra == termo_normalizado or
                    (len(termo_normalizado) >= 5 and palavra.startswith(termo_normalizado))
                    for palavra in palavras
                )
            if encontrado:
                termos_categoria.append(termo)
        if termos_categoria:
            categorias_encontradas.append(cat_nome)
            termos_encontrados.extend(termos_categoria)

    if not categorias_encontradas:
        categoria = "Geral / Outros"
    elif len(categorias_encontradas) > 1:
        categoria = f"Interdisciplinar ({' + '.join(categorias_encontradas)})"
    else:
        categoria = categorias_encontradas[0]
    return {
        "categoria": categoria,
        "areas_identificadas": "; ".join(categorias_encontradas),
        "termos_detectados": "; ".join(sorted(set(termos_encontrados))),
    }


def classificar_titulo(titulo: str, resumo: str = "") -> str:
    return classificar_artigo(titulo, resumo)["categoria"]

def processar_e_exportar_classificacao():
    pasta_data = Path(__file__).resolve().parent.parent / "Data"
    arquivos = [
        arquivo for arquivo in pasta_data.glob("artigos_*.csv")
        if not arquivo.name.startswith(("artigos_classificados_", "artigos_interdisciplinares_"))
    ]
    if not arquivos:
        print(f"⚠️ Nenhum arquivo CSV encontrado em {pasta_data} para classificar.")
        return

    arquivo_origem = max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime)
    arquivo_destino = arquivo_origem.with_name(f"artigos_classificados_{arquivo_origem.stem.removeprefix('artigos_')}.csv")

    print(f"📂 Lendo dataset: {arquivo_origem}")

    artigos_processados = []
    contagem_categorias = Counter()

    with open(arquivo_origem, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames.copy() if reader.fieldnames else []
        
        if "categoria" not in fieldnames:
            fieldnames.append("categoria")

        for row in reader:
            classificacao = classificar_artigo(row.get("titulo", ""), row.get("resumo", ""))
            row.update(classificacao)
            artigos_processados.append(row)
            contagem_categorias[classificacao["categoria"]] += 1

    with open(arquivo_destino, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(artigos_processados)

    print("\n" + "=" * 65)
    print("📊 DISTRIBUIÇÃO DOS ARTIGOS POR CATEGORIA CIENTÍFICA")
    print("=" * 65)
    total = len(artigos_processados)
    
    for cat, qtd in contagem_categorias.most_common():
        pct = (qtd / total) * 100 if total > 0 else 0
        print(f" 🔹 {cat}: {qtd} artigos ({pct:.1f}%)")

    print("\n" + "=" * 65)
    print(f"💾 Novo CSV classificado gerado: {arquivo_destino}")