import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import requests
from deep_translator import GoogleTranslator

def traduzir_termo(texto: str, origem: str = "auto", destino: str = "en") -> str:
    """Traduz o termo de busca para inglês para garantir máxima cobertura nas APIs científicas."""
    try:
        traducao = GoogleTranslator(source=origem, target=destino).translate(texto)
        return traducao
    except Exception as e:
        print(f"⚠️ Não foi possível traduzir o termo: {e}")
        return texto

def buscar_artigos_multilingue(termo_usuario: str, max_resultados: int = 3) -> List[Dict[str, Any]]:
    """
    Recebe um termo em qualquer idioma (ex: Português), traduz para o Inglês,
    executa a busca internacional e retorna os resultados.
    """
    # 1. Tradução da consulta do usuário para Inglês (Língua Franca Científica)
    termo_em_ingles = traduzir_termo(termo_usuario, origem="pt", destino="en")
    print(f"🔎 Termo original (PT): '{termo_usuario}'")
    print(f"🌐 Termo traduzido para a busca global (EN): '{termo_em_ingles}'\n")

    # 2. Requisição para a API
    base_url = "http://export.arxiv.org/api/query"
    params = {"search_query": f"all:{termo_em_ingles}", "start": 0, "max_results": max_resultados}
    headers = {"User-Agent": "ProjetoFundacao/1.0"}

    try:
        resposta = requests.get(base_url, params=params, headers=headers, timeout=10)
        resposta.raise_for_status()
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        return []

    # 3. Parsing dos dados
    root = ET.fromstring(resposta.content)
    namespace = {'atom': 'http://www.w3.org/2005/Atom'}
    artigos = []

    for entry in root.findall('atom:entry', namespace):
        titulo_en = entry.find('atom:title', namespace).text.strip().replace("\n", " ")
        resumo_en = entry.find('atom:summary', namespace).text.strip().replace("\n", " ")
        
        # Opcional: Traduzir o resumo de volta para Português para exibição ao usuário
        titulo_pt = traduzir_termo(titulo_en[:200], origem="en", destino="pt")

        artigos.append({
            "titulo_original": titulo_en,
            "titulo_portugues": titulo_pt,
            "resumo_en": resumo_en
        })

    return artigos


if __name__ == "__main__":
    # Testando busca digitada em Português
    termo_pesquisa = "astrobiologia"
    resultados = buscar_artigos_multilingue(termo_usuario=termo_pesquisa, max_resultados=2)

    print("=== RESULTADOS OBTIDOS DA BASE GLOBAL ===\n")
    for idx, art in enumerate(resultados, 1):
        print(f"Artigo #{idx}")
        print(f"📌 Título (Traduzido PT): {art['titulo_portugues']}")
        print(f"📄 Título (Original EN): {art['titulo_original']}")
        print(f"📝 Resumo EN (Trecho): {art['resumo_en'][:150]}...")
        print("-" * 60)