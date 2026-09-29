import unittest
import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook

from analise_csv_nativo import projetar_volume_publicacoes
from classificar_artigos import classificar_artigo
from massive_ingestion import (
    criar_registro,
    corresponde_ao_filtro,
    expandir_termo_busca,
    normalizar_doi,
    pontuar_relevancia,
    reconstruir_resumo_openalex,
)
from mineracao_termos import extrair_bigramas, extrair_padroes_especificos, tokenizar
from impact_prediction import analisar_risco_de_impacto, baixar_emdat_csv


class IngestionTests(unittest.TestCase):
    def test_normalizes_doi_urls(self):
        self.assertEqual(normalizar_doi("https://doi.org/10.1234/ABC."), "10.1234/abc")

    def test_reconstructs_openalex_abstract(self):
        self.assertEqual(
            reconstruir_resumo_openalex({"physics": [1], "mathematical": [0]}),
            "mathematical physics",
        )

    def test_portuguese_query_expands_for_english_catalogs(self):
        self.assertEqual(expandir_termo_busca("Terremoto Japão"), ["Terremoto Japão", "earthquake japan"])
        self.assertEqual(pontuar_relevancia("Terremoto Japão", "Earthquake in Japan", ""), 2.0)

    def test_brazil_translation_keeps_english_results(self):
        variantes = expandir_termo_busca("Terremoto Brasil")
        self.assertEqual(variantes, ["Terremoto Brasil", "earthquake brazil"])
        self.assertTrue(
            corresponde_ao_filtro(variantes[-1], "Earthquake in Brazil", "", "todos")
        )

    def test_all_terms_and_exact_phrase_are_distinct(self):
        self.assertTrue(corresponde_ao_filtro("earthquake Japan", "Earthquake in Japan", "", "todos"))
        self.assertFalse(corresponde_ao_filtro("earthquake Japan", "Earthquake in Chile", "", "todos"))
        self.assertTrue(corresponde_ao_filtro("origin of life", "The origin of life", "", "frase"))
        self.assertFalse(corresponde_ao_filtro("origin of life", "Origin and evolution of life", "", "frase"))

    def test_record_cleans_metadata_and_scores_relevance(self):
        record = criar_registro(
            "Earthquake Japan",
            "https://doi.org/10.1234/example",
            2024,
            "Crossref",
            resumo="<jats:p>Earthquake observations in Japan</jats:p>",
            termo_busca="Earthquake Japan",
        )
        self.assertEqual(record["doi"], "10.1234/example")
        self.assertEqual(record["resumo"], "Earthquake observations in Japan")
        self.assertEqual(record["relevancia"], 3.0)


class AnalysisTests(unittest.TestCase):
    def test_classifies_from_title_and_abstract(self):
        result = classificar_artigo(
            "Evolutionary dynamics of a population",
            "We model genetic change with differential equations.",
        )
        self.assertIn("Matemática & Modelagem", result["areas_identificadas"])
        self.assertIn("Biologia & Evolução", result["areas_identificadas"])
        self.assertTrue(result["categoria"].startswith("Interdisciplinar"))

    def test_bigrams_do_not_skip_stopwords(self):
        tokens = tokenizar("models of life")
        self.assertEqual(extrair_bigramas(tokens), [])
        self.assertEqual(extrair_bigramas(tokenizar("mathematical models of life")), ["mathematical models"])

    def test_mines_portuguese_math_patterns(self):
        counts = extrair_padroes_especificos(["Equações diferenciais em modelagem matemática"])
        self.assertEqual(counts["equacoes diferenciais"], 1)

    def test_publication_projection_requires_history(self):
        short_series = [{"ano": 2020}, {"ano": 2021}, {"ano": 2022}]
        self.assertEqual(projetar_volume_publicacoes(short_series), [])

        series = [
            {"ano": year}
            for year, count in [(2016, 2), (2017, 3), (2018, 4), (2019, 5), (2020, 6)]
            for _ in range(count)
        ]
        forecast = projetar_volume_publicacoes(series, anos_a_frente=2)
        self.assertEqual([row["ano"] for row in forecast], [2021, 2022])
        self.assertTrue(all(row["limite_inferior"] <= row["estimativa"] <= row["limite_superior"] for row in forecast))
        self.assertNotIn("probabilidade_evento", forecast[0])


class ImpactPredictionTests(unittest.TestCase):
    def test_downloads_latest_hdx_workbook_as_csv_with_source_metadata(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Year", "Country", "ISO", "Total Deaths"])
        worksheet.append(["#date +occurred", "#country +name", "#country +code", "#affected +ind +killed"])
        worksheet.append([2024, "Brazil", "BRA", 12])
        contenido = io.BytesIO()
        workbook.save(contenido)

        metadata_response = Mock()
        metadata_response.json.return_value = {
            "success": True,
            "result": {
                "resources": [{
                    "format": "XLSX",
                    "description": "Version: 2026-09-23",
                    "download_url": "https://example.test/emdat.xlsx",
                }]
            },
        }
        download_response = Mock()
        download_response.content = contenido.getvalue()

        with tempfile.TemporaryDirectory() as pasta_temporaria:
            with patch("impact_prediction.requests.get", side_effect=[metadata_response, download_response]):
                resultado = baixar_emdat_csv(pasta_temporaria)

            with open(resultado["caminho"], encoding="utf-8-sig", newline="") as arquivo:
                linhas = list(csv.reader(arquivo))
            metadados = json.loads(Path(resultado["metadados"]).read_text(encoding="utf-8"))

            self.assertEqual(resultado["versao"], "2026-09-23")
            self.assertEqual(resultado["linhas"], 1)
            self.assertEqual(linhas[2], ["2024", "Brazil", "BRA", "12"])
            self.assertIn("HDX", metadados["fonte"])

    def test_scores_impact_from_aligned_predictor_and_emdat_csvs(self):
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            pasta = Path(pasta_temporaria)
            caminho_preditores = pasta / "preditores.csv"
            caminho_emdat = pasta / "emdat.csv"
            paises = ("Brazil", "Japan", "Chile", "Peru", "Iceland")

            with caminho_preditores.open("w", newline="", encoding="utf-8") as arquivo:
                escritor = csv.writer(arquivo)
                escritor.writerow(("year", "location", "variable", "value", "unit"))
                for indice_pais, pais in enumerate(paises):
                    for ano in range(2000, 2025):
                        escritor.writerow((ano, pais, "solar irradiance", (ano + indice_pais) % 4, "W/m2"))

            with caminho_emdat.open("w", newline="", encoding="utf-8") as arquivo:
                escritor = csv.writer(arquivo)
                escritor.writerow(("Start Year", "Country", "Total Deaths", "Total Affected", "Total Damage ('000 US$)"))
                for indice_pais, pais in enumerate(paises):
                    for ano in range(2000, 2026):
                        valor_preditor_ano_anterior = (ano - 1 + indice_pais) % 4
                        mortes = 10 if pais != "Iceland" and ano > 2000 and valor_preditor_ano_anterior >= 2 else 0
                        escritor.writerow((ano, pais, mortes, 0, 0))

            progresso = []
            resultado = analisar_risco_de_impacto(
                "solar irradiance",
                str(caminho_preditores),
                str(caminho_emdat),
                horizonte=1,
                limite_mortes=1,
                limite_afetados=100000,
                limite_prejuizo_usd=1_000_000_000,
                progresso=lambda percentual, mensagem: progresso.append((percentual, mensagem)),
            )

            self.assertEqual(len(resultado["previsoes"]), len(paises))
            self.assertIn("iceland", {item["local"] for item in resultado["previsoes"]})
            self.assertEqual(resultado["ano_inicio_teste"], 2020)
            self.assertGreaterEqual(resultado["brier_score"], 0)
            self.assertLessEqual(resultado["brier_score"], 1)
            self.assertGreaterEqual(resultado["brier_base"], 0)
            self.assertLessEqual(resultado["brier_base"], 1)
            self.assertTrue(-10 <= resultado["habilidade_brier"] <= 1)
            self.assertTrue(all(0 <= item["probabilidade_impacto"] <= 1 for item in resultado["previsoes"]))
            percentuais = [percentual for percentual, _ in progresso]
            self.assertEqual(percentuais[0], 0)
            self.assertEqual(percentuais[-1], 100)
            self.assertEqual(percentuais, sorted(percentuais))
            self.assertTrue(any("Backtest temporal" in mensagem for _, mensagem in progresso))


if __name__ == "__main__":
    unittest.main()
