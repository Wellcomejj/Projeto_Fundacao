# Projeto Fundacao

Aplicacao desktop para busca, analise e classificacao de artigos cientificos.

## Estrutura

- `Modules/`: codigo ativo, testes e receita de empacotamento.
- `Data/`: CSVs de resultados e datasets gerados pelo pipeline.
- `Legacy/`: implementacoes antigas mantidas apenas para referencia.
- `.vscode/`: configuracoes locais do VS Code.

Pastas `build/`, `dist/` e caches Python sao geradas durante execucao ou empacotamento e nao fazem parte do codigo-fonte.

## Instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Executar a interface

```powershell
python Modules\gui_fundacao.py
```

## Executar os testes

```powershell
$env:PYTHONPATH = "Modules"
python -m unittest discover -s Modules -p "test_*.py" -v
```

## Pipeline

1. Buscar artigos.
2. Analisar o CSV mais recente em `Data/`.
3. Classificar areas cientificas.
4. Extrair artigos interdisciplinares.
5. Minerar termos.
6. Baixar PDFs de acesso aberto, quando disponiveis.

Os arquivos de dados sao escolhidos pelo timestamp de modificacao e permanecem em `Data/`.

## Cruzamento e probabilidade de impacto

O campo **Tema preditor** permite buscar publicacoes nas fontes academicas e selecionar uma variavel quantitativa para cruzamento. Use **Baixar EM-DAT atualizado** para obter o perfil oficial agregado do HDX; o aplicativo converte a planilha XLSX atual em CSV em `Data/`, ao lado das buscas, grava os metadados de origem/citacao e seleciona o CSV para a analise. O HDX Country Profiles contem totais anuais por pais e subtipo, nao os registros evento-a-evento do portal publico EM-DAT. A busca academica e exploratoria: artigos nao sao convertidos em medidas numericas pelo modelo. Selecione o CSV de series preditoras na interface. Os dados continuam sujeitos aos termos de uso EM-DAT e nao devem ser redistribuidos sem autorizacao.

O CSV de preditores deve ter cabecalho e estas colunas (nomes equivalentes em portugues tambem sao aceitos):

```csv
year,location,variable,value,unit
2020,Brazil,solar irradiance,182.4,W/m2
```

`year` tambem pode ser uma data. O tema precisa aparecer no nome da variavel; todos os termos informados sao exigidos. `location` deve corresponder ao nome do pais ou codigo ISO usado no EM-DAT.

O CSV de impactos pode ser o arquivo HDX gerado pelo botao ou um arquivo compativel, com ano, pais/ISO e ao menos uma medida de consequencia. O modelo reconhece cabecalhos do HDX como `Year`, `ISO`, `Total Deaths`, `Total Affected` e `Total Damage (USD, adjusted)`, assim como nomes do EM-DAT Public Table. Os valores sao agregados por pais e ano antes de aplicar os limiares; um evento positivo e definido quando mortes, afetados **ou** prejuizo alcancam o limite configurado.

O modelo agrega as medicoes anuais pela media, usa regressao logistica com variaveis padronizadas, valida em anos posteriores aos usados no treino e mostra o Brier score do backtest. A previsao condiciona nos ultimos valores medidos, assumindo que eles permanecem constantes; portanto e uma estimativa exploratoria, nao causal nem uma garantia de risco. Prejuizos monetarios devem estar em USD comparaveis entre anos; o app nao corrige inflacao. Cobertura temporal, localidades compativeis e ocorrencias suficientes sao necessarias. Resultados sao exportados para `Data/`.

## Empacotar com PyInstaller

A receita ativa esta em `Modules/ProjetoFundacao.spec`.

```powershell
pyinstaller Modules\ProjetoFundacao.spec
```
