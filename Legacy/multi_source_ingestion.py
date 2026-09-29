import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import requests
from deep_translator import GoogleTranslator

HEADERS = {
    "User-Agent": "ProjetoFundacao/1.0 (mailto:pesquisador@projetofundacao.org)"
}

def traduzir_e_otimizar_termo(texto: str) -> Dict[str, str]:
    """
    Traduz o termo e gera duas versões de busca:
    1. Estrita (frase exata)
    2. Ampliada (palavras-chave com operador OR)
    """
    try:
        termo_en = GoogleTranslator(source="auto", target="en").translate(texto)
    except Exception:
        termo_en = texto

    # Limpa pontuações e quebra em palavras chave individuais
    palavras = [p for p in termo_en.lower().replace("and", "").replace("or", "").split() if len(p) > 3]
    
    termo_ampliado = " OR ".join(palavras) if palavras else termo_en

    return {
        "estrito": termo_en,
        "ampliado": termo_ampliado
    }


# ==========================================
# 1. ADAPTADOR OTIMIZADO: arXiv
# ==========================================
def buscar_arxiv(consultas: Dict[str, str], max_resultados: int = 5) -> List[Dict[str, Any]]:
    url = "http://export.arxiv.org/api/query"
    artigos = []

    # Tentativa 1: Busca Estrita | Tentativa 2: Busca Ampliada
    for modo in ["estrito", "ampliado"]:
        termo = consultas[modo]
        params = {"search_query": f"all:{termo}", "start": 0, "max_results": max_resultados}
        
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                entries = root.findall('atom:entry', ns)
                
                for entry in entries:
                    titulo = entry.find('atom:title', ns).text.strip().replace("\n", " ")
                    resumo = entry.find('atom:summary', ns).text.strip().replace("\n", " ")
                    artigos.append({
                        "fonte": "arXiv",
                        "titulo": titulo,
                        "resumo": resumo[:250] + "..."
                    })
                
                # Se encontrou resultados suficientes na busca estrita, não precisa rodar a ampliada
                if len(artigos) >= 2:
                    break
        except Exception as e:
            print(f"⚠️ Erro arXiv ({modo}): {e}")

    return artigos


# ==========================================
# 2. ADAPTADOR OTIMIZADO: PubMed
# ==========================================
def buscar_pubmed(consultas: Dict[str, str], max_resultados: int = 5) -> List[Dict[str, Any]]:
    url_esearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    artigos = []

    for modo in ["estrito", "ampliado"]:
        termo = consultas[modo]
        params_search = {"db": "pubmed", "term": termo, "retmode": "json", "retmax": max_resultados}
        
        try:
            resp_search = requests.get(url_esearch, params=params_search, headers=HEADERS, timeout=10)
            data_search = resp_search.json()
            id_list = data_search.get("esearchresult", {}).get("idlist", [])
            
            if id_list:
                url_esummary = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                params_summary = {"db": "pubmed", "id": ",".join(id_list), "retmode": "json"}
                resp_summary = requests.get(url_esummary, params=summary_params if 'summary_params' in locals() else params_summary, headers=HEADERS, timeout=10)
                data_summary = resp_summary.json().get("result", {})

                for pmid in id_list:
                    item = data_summary.get(pmid, {})
                    titulo = item.get("title", "Sem título")
                    artigos.append({
                        "fonte": "PubMed",
                        "titulo": titulo,
                        "resumo": f"Registro localizado via PubMed (ID: {pmid})"
                    })
                
                if len(artigos) >= 2:
                    break
        except Exception as e:
            print(f"⚠️ Erro PubMed ({modo}): {e}")

    return artigos


# ==========================================
# 3. ADAPTADOR OTIMIZADO: Crossref
# ==========================================
def buscar_crossref(consultas: Dict[str, str], max_resultados: int = 5) -> List[Dict[str, Any]]:
    url = "https://api.crossref.org/works"
    artigos = []

    for modo in ["estrito", "ampliado"]:
        termo = consultas[modo]
        params = {"query": termo, "rows": max_resultados}
        
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                for item in items:
                    titulo = item.get("title", ["Sem título"])[0]
                    container = item.get("container-title", ["Revista Científica"])[0]
                    artigos.append({
                        "fonte": f"Crossref ({container})",
                        "titulo": titulo,
                        "resumo": f"Publicado em: {container}"
                    })
                
                if len(artigos) >= 2:
                    break
        except Exception as e:
            print(f"⚠️ Erro Crossref ({modo}): {e}")

    return artigos


# ==========================================
# MOTOR PRINCIPAL
# ==========================================
def buscar_em_todas_as_fontes(termo_usuario: str, max_por_fonte: int = 5) -> List[Dict[str, Any]]:
    consultas = traduzir_e_otimizar_termo(termo_usuario)
    
    print(f"🔎 Pesquisa: '{termo_usuario}'")
    print(f"🎯 Busca Estrita: '{consultas['estrito']}'")
    print(f"🌐 Busca Ampliada: '{consultas['ampliado']}'\n")

    resultados = []
    
    print("-> Consultado arXiv...")
    resultados.extend(buscar_arxiv(consultas, max_por_fonte))
    
    print("-> Consultado PubMed...")
    resultados.extend(buscar_pubmed(consultas, max_por_fonte))
    
    print("-> Consultado Crossref...")
    resultados.extend(buscar_crossref(consultas, max_por_fonte))

    return resultados


if __name__ == "__main__":
    # Teste com termo composto longo
    termo = "Terremoto Brasil"
    artigos = buscar_em_todas_as_fontes(termo, max_por_fonte=3)

    print(f"\n================ TOTAL DE ARTIGOS ENCONTRADOS: {len(artigos)} ================\n")
    for idx, art in enumerate(artigos, 1):
        print(f"#{idx} [{art['fonte']}]")
        print(f"📌 Título: {art['titulo']}")
        print(f"📝 Info: {art['resumo']}")
        print("-" * 70)