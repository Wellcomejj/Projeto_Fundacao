import csv
from pathlib import Path
from statistics import mean

def extrair_artigos_interdisciplinares():
    pasta_data = Path(__file__).resolve().parent.parent / "Data"
    arquivos = list(pasta_data.glob("artigos_classificados_*.csv"))
    
    if not arquivos:
        print("⚠️ Nenhum arquivo 'artigos_classificados_*.csv' encontrado.")
        print("💡 Execute a etapa de classificação primeiro.")
        return

    arquivo_origem = max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime)
    identificador = arquivo_origem.stem.removeprefix("artigos_classificados_")
    arquivo_destino = pasta_data / f"artigos_interdisciplinares_{identificador}.csv"

    print(f"📂 Processando dataset classificado: {arquivo_origem}")

    artigos_interdisciplinares = []

    with open(arquivo_origem, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames if reader.fieldnames else []

        for row in reader:
            areas = [area.strip() for area in row.get("areas_identificadas", "").split(";") if area.strip()]
            if not areas:
                categoria = row.get("categoria", "")
                if categoria.startswith("Interdisciplinar ("):
                    conteudo = categoria.partition("(")[2].rsplit(")", 1)[0]
                    areas = [area.strip() for area in conteudo.split("+")]
            if "Matemática & Modelagem" in areas and len(areas) > 1:
                row["areas_cruzadas"] = "; ".join(areas)
                artigos_interdisciplinares.append(row)

    if not artigos_interdisciplinares:
        print("⚠️ Nenhum artigo atendeu aos critérios de cruzamento interdisciplinar.")
        if "areas_cruzadas" not in fieldnames:
            fieldnames.append("areas_cruzadas")
        with open(arquivo_destino, mode="w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        print(f"Arquivo vazio atualizado para evitar resultados antigos: {arquivo_destino}")
        return arquivo_destino

    if "areas_cruzadas" not in fieldnames:
        fieldnames.append("areas_cruzadas")
    artigos_interdisciplinares.sort(
        key=lambda artigo: (
            int(artigo["citacoes"]) if str(artigo.get("citacoes", "")).isdigit() else -1,
            float(artigo.get("relevancia", 0) or 0),
        ),
        reverse=True,
    )

    with open(arquivo_destino, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(artigos_interdisciplinares)

    total = len(artigos_interdisciplinares)
    citacoes = [int(a["citacoes"]) for a in artigos_interdisciplinares if str(a.get("citacoes", "")).isdigit()]
    media_cit = mean(citacoes) if citacoes else None

    print("\n" + "=" * 70)
    print("SELECAO DE ARTIGOS INTERDISCIPLINARES COM MODELAGEM MATEMATICA")
    print("=" * 70)
    print(f"Total de artigos selecionados: {total}")
    if media_cit is not None:
        print(f"Media de citacoes onde disponivel: {media_cit:.1f} ({len(citacoes)} artigos)")
    else:
        print("Citacoes indisponiveis; nao foram substituidas por zero.")
    print(f"Dataset gerado: {arquivo_destino}\n")
    return arquivo_destino