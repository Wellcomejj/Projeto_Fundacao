import os
import re
import csv
import time
import requests
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from massive_ingestion import normalizar_doi

EMAIL_CONTATO = os.getenv("UNPAYWALL_EMAIL", "").strip()


def consultar_unpaywall(doi: str) -> Optional[str]:
    """
    Consulta a API do Unpaywall para obter o link direto do PDF gratuito.
    """
    if not EMAIL_CONTATO:
        print("Configure UNPAYWALL_EMAIL para habilitar consultas ao Unpaywall.")
        return None
    doi_limpo = normalizar_doi(doi)
    if not doi_limpo:
        return None
    url = f"https://api.unpaywall.org/v2/{quote(doi_limpo, safe='')}"
    try:
        response = requests.get(
            url,
            params={"email": EMAIL_CONTATO},
            headers={"User-Agent": f"ProjetoFundacaoBot/1.0 (mailto:{EMAIL_CONTATO})"},
            timeout=15,
        )
        if response.status_code == 200:
            dados = response.json()
            localizacoes = [dados.get("best_oa_location")] + dados.get("oa_locations", [])
            for localizacao in localizacoes:
                if localizacao and localizacao.get("url_for_pdf"):
                    return localizacao["url_for_pdf"]
        else:
            print(f"Unpaywall retornou HTTP {response.status_code} para DOI {doi_limpo}.")
    except requests.RequestException as erro:
        print(f"Erro ao consultar Unpaywall para DOI {doi_limpo}: {erro}")
    return None


def baixar_pdf(url_pdf: str, caminho_salvar: str) -> bool:
    """
    Faz o download do arquivo PDF a partir do link retornado.
    """
    temporario = Path(f"{caminho_salvar}.part")
    try:
        with requests.get(url_pdf, timeout=30, stream=True, allow_redirects=True) as res:
            if res.status_code != 200:
                return False
            iterador = res.iter_content(chunk_size=8192)
            primeiro_bloco = next(iterador, b"")
            if not primeiro_bloco.startswith(b"%PDF-"):
                return False
            with temporario.open("wb") as arquivo:
                arquivo.write(primeiro_bloco)
                for bloco in iterador:
                    if bloco:
                        arquivo.write(bloco)
        temporario.replace(caminho_salvar)
        return True
    except (requests.RequestException, OSError) as erro:
        print(f"Falha no download do PDF: {erro}")
        temporario.unlink(missing_ok=True)
        return False


def baixar_pdfs_unpaywall(pasta_destino: str = "PDFs_Fundacao", arquivo_csv: str = None):
    """
    Lê o CSV mais recente e baixa os PDFs disponíveis via Unpaywall.
    """
    diretorio_raiz = Path(__file__).resolve().parent.parent
    pasta_data = diretorio_raiz / "Data"
    if arquivo_csv:
        caminho_csv = Path(arquivo_csv)
        if not caminho_csv.is_absolute():
            caminho_csv = diretorio_raiz / caminho_csv
    else:
        arquivos = [
            arquivo for arquivo in pasta_data.glob("artigos_*.csv")
            if not arquivo.name.startswith(("artigos_classificados_", "artigos_interdisciplinares_"))
        ]
        caminho_csv = max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime) if arquivos else None

    if caminho_csv is None or not caminho_csv.exists():
        print(f"Nenhum CSV de ingestao encontrado em {pasta_data}.")
        return
    if not EMAIL_CONTATO:
        print("Configure UNPAYWALL_EMAIL antes de consultar ou baixar artigos.")
        return

    pasta_pdf = Path(pasta_destino)
    if not pasta_pdf.is_absolute():
        pasta_pdf = diretorio_raiz / pasta_pdf
    pasta_pdf.mkdir(parents=True, exist_ok=True)
    print(f"Lendo dataset: {caminho_csv}\n")

    total_com_doi = 0
    baixados = 0

    with caminho_csv.open(mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doi = normalizar_doi(row.get("doi", ""))
            titulo = row.get("titulo", "artigo").strip() or "artigo"

            if doi:
                total_com_doi += 1
                nome_limpo = re.sub(r'[\\/*?:"<>|]', "", titulo)[:80].strip() or doi.replace("/", "_")
                caminho_pdf = pasta_pdf / f"{nome_limpo}.pdf"

                if caminho_pdf.exists():
                    print(f"[Ja baixado] {caminho_pdf.name}")
                    continue

                print(f"Consultando Unpaywall: {doi}")
                url_pdf = consultar_unpaywall(doi)

                if url_pdf:
                    if baixar_pdf(url_pdf, str(caminho_pdf)):
                        print(f"PDF salvo: {caminho_pdf.name}\n")
                        baixados += 1
                    else:
                        print("Falha ao baixar o PDF desta localizacao.\n")
                else:
                    print("Nenhuma localizacao com PDF OA foi encontrada.\n")

                time.sleep(0.5)

    print("=" * 65)
    print("RESUMO DO DOWNLOAD DE PDFs (UNPAYWALL)")
    print("=" * 65)
    print(f"Total de artigos com DOI analisados: {total_com_doi}")
    print(f"PDFs OA baixados: {baixados}")
    print(f"Pasta de destino: {pasta_pdf}")
    print("=" * 65)

if __name__ == "__main__":
    baixar_pdfs_unpaywall()