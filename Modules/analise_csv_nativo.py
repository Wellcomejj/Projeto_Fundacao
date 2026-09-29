import csv
from pathlib import Path
from collections import Counter
from datetime import datetime
from math import sqrt
from statistics import mean, median

def carregar_csv_mais_recente():
    """Localiza e carrega o arquivo CSV mais recente gerado pela ingestão."""
    pasta_data = Path(__file__).resolve().parent.parent / "Data"
    arquivos = [
        arquivo for arquivo in pasta_data.glob("artigos_*.csv")
        if not arquivo.name.startswith(("artigos_classificados_", "artigos_interdisciplinares_"))
    ]
    if not arquivos:
        print(f"⚠️ Nenhum arquivo CSV encontrado em {pasta_data}.")
        return None, []

    # Pega o arquivo mais recente
    arquivo_mais_recente = max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime)
    print(f"📂 Carregando dados de: {arquivo_mais_recente}\n")

    artigos = []
    with open(arquivo_mais_recente, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Tratamento básico de tipos numéricos
            try:
                row["ano"] = int(row["ano"])
            except (TypeError, ValueError):
                row["ano"] = None

            try:
                valor_citacoes = (row.get("citacoes") or "").strip()
                row["citacoes"] = int(valor_citacoes) if valor_citacoes else None
            except (TypeError, ValueError):
                row["citacoes"] = None

            row["idioma_busca"] = row.get("idioma_busca") or row.get("idioma", "")

            artigos.append(row)

    return arquivo_mais_recente, artigos


def projetar_volume_publicacoes(artigos, anos_a_frente=5):
    """Projeta contagens bibliográficas; não representa probabilidade de eventos científicos."""
    contagens = Counter(
        artigo["ano"] for artigo in artigos
        if isinstance(artigo.get("ano"), int) and artigo["ano"] < datetime.now().year
    )
    if len(contagens) < 5:
        return []

    inicio = min(contagens)
    fim = max(contagens)
    anos = list(range(inicio, fim + 1))
    valores = [contagens.get(ano, 0) for ano in anos]
    media_ano = mean(anos)
    media_valor = mean(valores)
    soma_quadrados = sum((ano - media_ano) ** 2 for ano in anos)
    if soma_quadrados == 0:
        return []
    inclinacao = sum((ano - media_ano) * (valor - media_valor)
                     for ano, valor in zip(anos, valores)) / soma_quadrados
    intercepto = media_valor - inclinacao * media_ano
    erros = [valor - (intercepto + inclinacao * ano) for ano, valor in zip(anos, valores)]
    erro_padrao = sqrt(sum(erro * erro for erro in erros) / max(1, len(anos) - 2))

    projecoes = []
    for ano in range(fim + 1, fim + anos_a_frente + 1):
        estimativa = max(0.0, intercepto + inclinacao * ano)
        margem = 1.96 * erro_padrao * sqrt(1 + 1 / len(anos) + (ano - media_ano) ** 2 / soma_quadrados)
        projecoes.append({
            "ano": ano,
            "estimativa": round(estimativa, 1),
            "limite_inferior": round(max(0.0, estimativa - margem), 1),
            "limite_superior": round(estimativa + margem, 1),
        })
    return projecoes


def analisar_dataset(artigos):
    """Resume metadados bibliográficos e uma tendência exploratória de publicações."""
    if not artigos:
        return

    total_artigos = len(artigos)
    fontes_count = Counter(a.get("fonte", "Não informado").split(" [")[0] for a in artigos)
    idiomas_count = Counter(a.get("idioma") or "Não informado" for a in artigos)
    anos_validos = [a["ano"] for a in artigos if isinstance(a.get("ano"), int)]
    decadas = Counter((ano // 10) * 10 for ano in anos_validos) if anos_validos else {}
    citacoes = [a["citacoes"] for a in artigos if isinstance(a.get("citacoes"), int)]
    top_artigos = sorted(
        (artigo for artigo in artigos if isinstance(artigo.get("citacoes"), int)),
        key=lambda artigo: artigo["citacoes"],
        reverse=True,
    )[:5]

    print("=" * 65)
    print("RELATORIO ESTATISTICO DO DATASET (PROJETO FUNDACAO)")
    print("=" * 65)
    print(f"Total de artigos unicos analisados: {total_artigos}\n")

    print("Distribuicao por origem de ingestao:")
    for fonte, qtd in fontes_count.items():
        pct = (qtd / total_artigos) * 100
        print(f"   - {fonte}: {qtd} artigos ({pct:.1f}%)")

    print("\nDistribuicao por idioma dos registros:")
    for lang, qtd in idiomas_count.items():
        pct = (qtd / total_artigos) * 100
        print(f"   - [{lang.upper()}]: {qtd} artigos ({pct:.1f}%)")

    if anos_validos:
        print("\nDistribuicao temporal por decada:")
        for decada in sorted(decadas.keys()):
            qtd = decadas[decada]
            pct = (qtd / len(anos_validos)) * 100
            print(f"   - Decada de {decada}s: {qtd} artigos ({pct:.1f}%)")

    print("\nMetricas de citacoes:")
    if citacoes:
        print(f"   - Registros com citacoes disponiveis: {len(citacoes)} de {total_artigos}")
        print(f"   - Media: {mean(citacoes):.2f}")
        print(f"   - Mediana: {median(citacoes):.1f}")
    else:
        print("   - Indisponivel nas fontes deste conjunto; valores ausentes nao sao tratados como zero.")

    if top_artigos:
        print("\nArtigos com maior contagem de citacoes reportada pelas fontes:")
        for idx, art in enumerate(top_artigos, 1):
            print(f"   {idx}. [{art['citacoes']} cit.] ({art['ano']}) {art['titulo']}")

    projecoes = projetar_volume_publicacoes(artigos)
    print("\nTendencia exploratoria do volume de publicacoes:")
    if projecoes:
        print("   Projecao linear de registros por ano; nao estima a probabilidade de eventos do mundo real.")
        for projecao in projecoes:
            print(
                f"   - {projecao['ano']}: {projecao['estimativa']} registros "
                f"(faixa residual indicativa: {projecao['limite_inferior']}-{projecao['limite_superior']})"
            )
    else:
        print("   Serie historica insuficiente: sao necessarios ao menos cinco anos completos de dados.")

    print("=" * 65)


if __name__ == "__main__":
    nome_arq, dados = carregar_csv_mais_recente()
    if dados:
        analisar_dataset(dados)