import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import sys
import asyncio
import queue
from datetime import datetime
from pathlib import Path

# Importa as funções dos scripts criados anteriormente
try:
    from massive_ingestion import executar_busca_artigos, exportar_para_csv
    from analise_csv_nativo import carregar_csv_mais_recente, analisar_dataset
    from classificar_artigos import processar_e_exportar_classificacao
    from extrair_interdisciplinares import extrair_artigos_interdisciplinares
    from mineracao_termos import minerar_termos_interdisciplinares
    from unpaywall_downloader import baixar_pdfs_unpaywall
    from impact_prediction import analisar_risco_de_impacto, baixar_emdat_csv
except ImportError as e:
    raise RuntimeError("Não foi possível carregar os módulos do Projeto Fundação.") from e


class RedirecionadorTexto:
    """Redireciona os 'prints' do Python direto para a caixa de texto da GUI."""
    def __init__(self, widget_texto):
        self.widget_texto = widget_texto
        self.fila = queue.Queue()

    def write(self, texto):
        self.fila.put(texto)

    def flush(self):
        pass


class AppProjetoFundacao(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Projeto Fundação | Busca científica")
        self.geometry("860x660")
        self.minsize(760, 620)

        # Configura tema visual
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self._criar_componentes()

        self._stdout_original = sys.stdout
        self._redirecionador = RedirecionadorTexto(self.txt_console)
        self._tarefas_concluidas = queue.Queue()
        self._eventos_progresso = queue.Queue()
        self._trabalho_ativo = False
        self._fechando = False
        sys.stdout = self._redirecionador
        self.after(100, self._atualizar_console)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

    def _criar_componentes(self):
        # Header / Título
        frame_header = ttk.Frame(self, padding=10)
        frame_header.pack(fill=tk.X)
        lbl_titulo = ttk.Label(
            frame_header, 
            text="Projeto Fundação | Busca científica", 
            font=("Segoe UI", 15, "bold")
        )
        lbl_titulo.pack(side=tk.LEFT)

        frame_params = ttk.LabelFrame(self, text="Busca", padding=12)
        frame_params.pack(fill=tk.X, padx=10, pady=5)
        frame_params.columnconfigure(1, weight=1)

        ttk.Label(frame_params, text="Tema, palavra ou frase").grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=6
        )
        self.ent_termo = ttk.Entry(frame_params)
        self.ent_termo.insert(0, "origem da vida")
        self.ent_termo.grid(row=0, column=1, columnspan=5, sticky=tk.EW, padx=5, pady=6)
        self.ent_termo.bind("<Return>", lambda _evento: self._acao_ingestao())

        ttk.Label(frame_params, text="Correspondência").grid(
            row=1, column=0, sticky=tk.W, padx=5, pady=6
        )
        self.var_modo_busca = tk.StringVar(value="Todos os termos")
        self.cmb_modo_busca = ttk.Combobox(
            frame_params,
            textvariable=self.var_modo_busca,
            values=("Todos os termos", "Frase exata"),
            state="readonly",
            width=18,
        )
        self.cmb_modo_busca.grid(row=1, column=1, sticky=tk.W, padx=5, pady=6)

        ttk.Label(frame_params, text="De").grid(row=1, column=2, sticky=tk.E, padx=(12, 4), pady=6)
        self.ent_ano_inicio = ttk.Entry(frame_params, width=10)
        self.ent_ano_inicio.insert(0, "1950")
        self.ent_ano_inicio.grid(row=1, column=3, sticky=tk.W, padx=4, pady=6)

        ttk.Label(frame_params, text="Até").grid(row=1, column=4, sticky=tk.E, padx=(12, 4), pady=6)
        self.ent_ano_fim = ttk.Entry(frame_params, width=10)
        self.ent_ano_fim.insert(0, str(datetime.now().year))
        self.ent_ano_fim.grid(row=1, column=5, sticky=tk.W, padx=4, pady=6)

        ttk.Label(frame_params, text="Máximo de artigos").grid(
            row=2, column=0, sticky=tk.W, padx=5, pady=(8, 2)
        )
        self.ent_meta = ttk.Entry(frame_params, width=10)
        self.ent_meta.insert(0, "1500")
        self.ent_meta.grid(row=2, column=1, sticky=tk.W, padx=5, pady=(8, 2))

        self.var_somente_oa = tk.BooleanVar(value=False)
        self.chk_somente_oa = ttk.Checkbutton(
            frame_params,
            text="Somente texto completo aberto",
            variable=self.var_somente_oa,
        )
        self.chk_somente_oa.grid(row=2, column=2, columnspan=3, sticky=tk.W, padx=8, pady=(8, 2))

        self.btn_ingestao = ttk.Button(
            frame_params, text="Buscar artigos", style="Primary.TButton", command=self._acao_ingestao
        )
        self.btn_ingestao.grid(row=2, column=5, sticky=tk.E, padx=5, pady=(8, 2))
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 7))

        frame_cruzamento = ttk.LabelFrame(self, text="Cruzamento e probabilidade de impacto", padding=10)
        frame_cruzamento.pack(fill=tk.X, padx=10, pady=5)
        frame_cruzamento.columnconfigure(1, weight=1)
        frame_cruzamento.columnconfigure(3, weight=1)

        ttk.Label(frame_cruzamento, text="Tema preditor").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.ent_tema_preditor = ttk.Entry(frame_cruzamento)
        self.ent_tema_preditor.grid(row=0, column=1, columnspan=3, sticky=tk.EW, padx=4, pady=4)
        self.ent_tema_preditor.insert(0, "solar irradiance")
        ttk.Label(frame_cruzamento, text="Horizonte (anos)").grid(row=0, column=4, sticky=tk.E, padx=4, pady=4)
        self.var_horizonte = tk.StringVar(value="1")
        ttk.Spinbox(frame_cruzamento, from_=1, to=100, textvariable=self.var_horizonte, width=7).grid(
            row=0, column=5, sticky=tk.W, padx=4, pady=4
        )

        ttk.Label(frame_cruzamento, text="Séries preditoras CSV").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
        self.var_arquivo_preditores = tk.StringVar()
        ttk.Entry(frame_cruzamento, textvariable=self.var_arquivo_preditores).grid(
            row=1, column=1, columnspan=4, sticky=tk.EW, padx=4, pady=4
        )
        ttk.Button(frame_cruzamento, text="Selecionar...", command=self._selecionar_preditores).grid(
            row=1, column=5, sticky=tk.EW, padx=4, pady=4
        )

        ttk.Label(frame_cruzamento, text="Impactos EM-DAT CSV").grid(row=2, column=0, sticky=tk.W, padx=4, pady=4)
        self.var_arquivo_emdat = tk.StringVar()
        ttk.Entry(frame_cruzamento, textvariable=self.var_arquivo_emdat).grid(
            row=2, column=1, columnspan=4, sticky=tk.EW, padx=4, pady=4
        )
        ttk.Button(frame_cruzamento, text="Selecionar...", command=self._selecionar_emdat).grid(
            row=2, column=5, sticky=tk.EW, padx=4, pady=4
        )

        ttk.Label(frame_cruzamento, text="Mortes ≥").grid(row=3, column=0, sticky=tk.E, padx=4, pady=4)
        self.ent_limite_mortes = ttk.Entry(frame_cruzamento, width=10)
        self.ent_limite_mortes.insert(0, "100")
        self.ent_limite_mortes.grid(row=3, column=1, sticky=tk.W, padx=4, pady=4)
        ttk.Label(frame_cruzamento, text="Afetados ≥").grid(row=3, column=2, sticky=tk.E, padx=4, pady=4)
        self.ent_limite_afetados = ttk.Entry(frame_cruzamento, width=12)
        self.ent_limite_afetados.insert(0, "100000")
        self.ent_limite_afetados.grid(row=3, column=3, sticky=tk.W, padx=4, pady=4)
        ttk.Label(frame_cruzamento, text="Prejuízo USD ≥").grid(row=3, column=4, sticky=tk.E, padx=4, pady=4)
        self.ent_limite_prejuizo = ttk.Entry(frame_cruzamento, width=14)
        self.ent_limite_prejuizo.insert(0, "1000000000")
        self.ent_limite_prejuizo.grid(row=3, column=5, sticky=tk.W, padx=4, pady=4)

        self.btn_baixar_emdat = ttk.Button(
            frame_cruzamento,
            text="Baixar EM-DAT atualizado",
            command=self._acao_baixar_emdat,
        )
        self.btn_baixar_emdat.grid(row=4, column=0, columnspan=3, sticky=tk.EW, padx=4, pady=(6, 2))
        self.btn_buscar_tema = ttk.Button(
            frame_cruzamento,
            text="Buscar publicações do tema",
            command=self._acao_buscar_tema_preditor,
        )
        self.btn_buscar_tema.grid(row=4, column=3, columnspan=2, sticky=tk.EW, padx=4, pady=(6, 2))
        self.btn_prever_impacto = ttk.Button(
            frame_cruzamento,
            text="Estimar probabilidade",
            style="Primary.TButton",
            command=self._acao_previsao_impacto,
        )
        self.btn_prever_impacto.grid(row=4, column=5, sticky=tk.EW, padx=4, pady=(6, 2))

        self.var_percentual_cruzamento = tk.StringVar(value="0%")
        ttk.Label(frame_cruzamento, textvariable=self.var_percentual_cruzamento, width=5).grid(
            row=5, column=0, sticky=tk.W, padx=4, pady=(7, 1)
        )
        self.barra_cruzamento = ttk.Progressbar(frame_cruzamento, mode="determinate", maximum=100, value=0)
        self.barra_cruzamento.grid(row=5, column=1, columnspan=5, sticky=tk.EW, padx=4, pady=(7, 1))
        self.var_etapa_cruzamento = tk.StringVar(value="Pronto para cruzar os dados.")
        ttk.Label(frame_cruzamento, textvariable=self.var_etapa_cruzamento).grid(
            row=6, column=0, columnspan=6, sticky=tk.W, padx=4, pady=(1, 3)
        )

        frame_status = ttk.Frame(self, padding=(12, 2, 12, 4))
        frame_status.pack(fill=tk.X)
        self.var_status_busca = tk.StringVar(value="Pronto para buscar.")
        self.lbl_status_busca = ttk.Label(frame_status, textvariable=self.var_status_busca)
        self.lbl_status_busca.pack(side=tk.LEFT, padx=(0, 8))
        self.barra_busca = ttk.Progressbar(frame_status, mode="indeterminate", length=180)
        self.barra_busca.pack(side=tk.LEFT, fill=tk.X, expand=True)

        frame_botoes = ttk.LabelFrame(self, text="Análises do CSV mais recente", padding=8)
        frame_botoes.pack(fill=tk.X, padx=10, pady=5)
        for coluna in range(3):
            frame_botoes.columnconfigure(coluna, weight=1)

        self.btn_analise = ttk.Button(frame_botoes, text="Tendências", command=self._acao_analise)
        self.btn_analise.grid(row=0, column=0, sticky=tk.EW, padx=4, pady=4)

        self.btn_classificar = ttk.Button(frame_botoes, text="Classificar áreas", command=self._acao_classificar)
        self.btn_classificar.grid(row=0, column=1, sticky=tk.EW, padx=4, pady=4)

        self.btn_extrair = ttk.Button(frame_botoes, text="Interdisciplinares", command=self._acao_extrair)
        self.btn_extrair.grid(row=0, column=2, sticky=tk.EW, padx=4, pady=4)

        self.btn_minerar = ttk.Button(frame_botoes, text="Minerar termos", command=self._acao_minerar)
        self.btn_minerar.grid(row=1, column=0, sticky=tk.EW, padx=4, pady=4)

        self.btn_pdfs = ttk.Button(frame_botoes, text="Baixar PDFs OA", command=self._acao_baixar_pdfs)
        self.btn_pdfs.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=4)

        btn_limpar = ttk.Button(frame_botoes, text="Limpar logs", command=self._limpar_console)
        btn_limpar.grid(row=1, column=2, sticky=tk.EW, padx=4, pady=4)
        self._botoes_trabalho = [
            self.btn_ingestao,
            self.btn_baixar_emdat,
            self.btn_buscar_tema,
            self.btn_prever_impacto,
            self.btn_analise,
            self.btn_classificar,
            self.btn_extrair,
            self.btn_minerar,
            self.btn_pdfs,
        ]

        frame_console = ttk.LabelFrame(self, text="Resultados e status", padding=8)
        frame_console.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.txt_console = scrolledtext.ScrolledText(
            frame_console, 
            wrap=tk.WORD, 
            font=("Consolas", 9),
            bg="#1e1e1e", 
            fg="#d4d4d4",
            insertbackground="white"
        )
        self.txt_console.pack(fill=tk.BOTH, expand=True)

    def _limpar_console(self):
        self.txt_console.delete("1.0", tk.END)

    def _selecionar_preditores(self):
        caminho = filedialog.askopenfilename(
            title="Selecionar séries quantitativas preditoras",
            initialdir=Path(__file__).resolve().parent.parent / "Data",
            filetypes=(("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")),
        )
        if caminho:
            self.var_arquivo_preditores.set(caminho)

    def _selecionar_emdat(self):
        pasta_emdat = Path(__file__).resolve().parent.parent / "Data"
        caminho = filedialog.askopenfilename(
            title="Selecionar catálogo de impactos EM-DAT",
            initialdir=pasta_emdat if pasta_emdat.exists() else pasta_emdat.parent,
            filetypes=(("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")),
        )
        if caminho:
            self.var_arquivo_emdat.set(caminho)

    def _acao_baixar_emdat(self):
        pasta_emdat = Path(__file__).resolve().parent.parent / "Data"
        if not self._iniciar_trabalho("Baixando e preparando EM-DAT..."):
            return

        def rodar():
            print("=" * 65)
            print("BAIXANDO PERFIL EM-DAT COUNTRY PROFILES PELO HDX")
            print("=" * 65)
            resultado = baixar_emdat_csv(pasta_emdat)
            print(f"Versão EM-DAT: {resultado['versao']}")
            print(f"Registros CSV: {resultado['linhas']}")
            print(f"CSV salvo em: {resultado['caminho']}")
            print(f"Origem e citação: {resultado['metadados']}")
            print("Fonte: HDX EM-DAT Country Profiles; dados agregados por ano, país e subtipo.")
            return resultado

        self._executar_em_thread(
            rodar,
            ao_sucesso=lambda resultado: self.var_arquivo_emdat.set(str(resultado["caminho"])),
            ao_concluir=lambda erro: self._finalizar_trabalho(erro, "Catálogo EM-DAT atualizado."),
        )

    def _acao_previsao_impacto(self):
        tema = self.ent_tema_preditor.get().strip()
        arquivo_preditores = self.var_arquivo_preditores.get().strip()
        arquivo_emdat = self.var_arquivo_emdat.get().strip()
        try:
            horizonte = int(self.var_horizonte.get())
            limite_mortes = float(self.ent_limite_mortes.get().strip())
            limite_afetados = float(self.ent_limite_afetados.get().strip())
            limite_prejuizo = float(self.ent_limite_prejuizo.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "Informe horizonte e limiares numéricos válidos.")
            return
        if not tema:
            messagebox.showwarning("Aviso", "Informe o tema das séries preditoras.")
            return
        if not Path(arquivo_preditores).is_file() or not Path(arquivo_emdat).is_file():
            messagebox.showwarning("Aviso", "Selecione os CSVs de séries preditoras e de impactos EM-DAT.")
            return
        if not self._iniciar_trabalho("Preparando cruzamento e estimativa...", determinado=True):
            return

        def rodar():
            print("=" * 65)
            print(f"CRUZAMENTO DE IMPACTO | tema: {tema} | horizonte: {horizonte} ano(s)")
            print("=" * 65)
            resultado = analisar_risco_de_impacto(
                tema,
                arquivo_preditores,
                arquivo_emdat,
                horizonte=horizonte,
                limite_mortes=limite_mortes,
                limite_afetados=limite_afetados,
                limite_prejuizo_usd=limite_prejuizo,
                pasta_saida=Path(__file__).resolve().parent.parent / "Data",
                progresso=lambda percentual, mensagem: self._eventos_progresso.put((percentual, mensagem)),
            )
            print(
                f"Backtest temporal a partir de {resultado['ano_inicio_teste']}; "
                f"Brier do modelo: {resultado['brier_score']:.4f}; "
                f"referência histórica: {resultado['brier_base']:.4f}; "
                f"habilidade Brier: {resultado['habilidade_brier']:.4f} "
                "(positiva indica melhora sobre a referência)."
            )
            print("Equação: logit(p) = intercepto + soma(coeficiente padronizado × variável z).")
            print(f"Intercepto: {resultado['intercepto']:.4f}")
            for variavel, coeficiente in resultado["coeficientes_padronizados"].items():
                print(f"  {variavel}: {coeficiente:+.4f}")
            print(f"Premissa: {resultado['premissa']}")
            print("Probabilidade estimada por localidade para o período futuro selecionado:")
            for previsao in resultado["previsoes"][:20]:
                percentual = previsao["probabilidade_impacto"] * 100
                print(f"  {previsao['local']} (último dado {previsao['ultimo_ano_observado']}): {percentual:.1f}%")
            print(f"CSV de resultados: {resultado['arquivo_saida']}")

        self._executar_em_thread(
            rodar,
            ao_concluir=lambda erro: self._finalizar_trabalho(erro, "Estimativa concluída; consulte métricas e logs."),
        )

    def _acao_buscar_tema_preditor(self):
        tema = self.ent_tema_preditor.get().strip()
        try:
            meta = int(self.ent_meta.get().strip())
            ano_inicio = int(self.ent_ano_inicio.get().strip())
            ano_fim = int(self.ent_ano_fim.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "Informe meta e período válidos na busca principal.")
            return
        if not tema:
            messagebox.showwarning("Aviso", "Informe o tema preditor.")
            return
        if meta < 1 or ano_inicio < 1 or ano_fim < ano_inicio or ano_fim > datetime.now().year:
            messagebox.showerror("Erro", "A meta ou o período da busca principal é inválido.")
            return

        modo_busca = "frase" if self.var_modo_busca.get() == "Frase exata" else "todos"
        somente_acesso_aberto = self.var_somente_oa.get()
        if not self._iniciar_trabalho("Buscando publicações do tema preditor..."):
            return

        def rodar():
            print("=" * 65)
            print(f"BUSCA DO TEMA PREDITOR: {tema} | {ano_inicio}-{ano_fim} | meta {meta}")
            print("=" * 65)
            artigos = asyncio.run(executar_busca_artigos(
                tema,
                meta_total_artigos=meta,
                faixas_temporais=[(ano_inicio, ano_fim)],
                modo_busca=modo_busca,
                somente_acesso_aberto=somente_acesso_aberto,
            ))
            if artigos:
                exportar_para_csv(artigos, termo_pesquisa=tema)
            else:
                print("Nenhuma publicação encontrada para o tema preditor.")

        self._executar_em_thread(
            rodar,
            ao_concluir=lambda erro: self._finalizar_trabalho(erro, "Busca do tema preditor finalizada."),
        )

    def _atualizar_console(self):
        partes = []
        while True:
            try:
                partes.append(self._redirecionador.fila.get_nowait())
            except queue.Empty:
                break
        if partes:
            self.txt_console.insert(tk.END, "".join(partes))
            self.txt_console.see(tk.END)
        while True:
            try:
                percentual, mensagem = self._eventos_progresso.get_nowait()
            except queue.Empty:
                break
            self._atualizar_progresso(percentual, mensagem)
        while True:
            try:
                callback, erro = self._tarefas_concluidas.get_nowait()
            except queue.Empty:
                break
            callback(erro)
        self.after(100, self._atualizar_console)

    def _fechar(self):
        self._fechando = True
        sys.stdout = self._stdout_original
        self.destroy()

    def _executar_em_thread(self, funcao_alvo, *args, ao_concluir=None, ao_sucesso=None):
        """Executa a tarefa em segundo plano para não travar a interface visual."""
        def wrapper():
            erro = None
            resultado = None
            try:
                resultado = funcao_alvo(*args)
            except Exception as ex:
                erro = ex
                print(f"\n❌ Ocorreu um erro durante a execução: {ex}")
            finally:
                if ao_sucesso and erro is None:
                    self._tarefas_concluidas.put((ao_sucesso, resultado))
                if ao_concluir:
                    self._tarefas_concluidas.put((ao_concluir, erro))
        
        t = threading.Thread(target=wrapper, daemon=True)
        t.start()

    def _executar_tarefa_com_barra(self, funcao_alvo, mensagem, mensagem_final):
        if not self._iniciar_trabalho(mensagem):
            return
        self._executar_em_thread(
            funcao_alvo,
            ao_concluir=lambda erro: self._finalizar_trabalho(erro, mensagem_final),
        )

    def _definir_busca_em_andamento(self, em_andamento, erro=None):
        if em_andamento:
            return self._iniciar_trabalho("Buscando artigos...")
        else:
            self._finalizar_trabalho(erro, "Busca finalizada. Consulte os resultados e logs.")
            return True

    def _iniciar_trabalho(self, mensagem, determinado=False):
        if self._fechando or self._trabalho_ativo:
            return False
        self._trabalho_ativo = True
        self.var_status_busca.set(mensagem)
        self.barra_busca.stop()
        if determinado:
            self.barra_busca.configure(mode="determinate", maximum=100, value=0)
        else:
            self.barra_busca.configure(mode="indeterminate", value=0)
            self.barra_busca.start(12)
        for botao in self._botoes_trabalho:
            botao.configure(state=tk.DISABLED)
        return True

    def _atualizar_progresso(self, percentual, mensagem):
        if self._fechando or not self._trabalho_ativo:
            return
        self.barra_busca.stop()
        self.barra_busca.configure(mode="determinate", maximum=100)
        self.barra_busca["value"] = max(0, min(100, percentual))
        self.var_status_busca.set(mensagem)

    def _finalizar_trabalho(self, erro=None, mensagem_sucesso="Tarefa concluída."):
        if self._fechando:
            return
        self._trabalho_ativo = False
        self.barra_busca.stop()
        self.barra_busca.configure(mode="indeterminate", value=0)
        for botao in self._botoes_trabalho:
            botao.configure(state=tk.NORMAL)
        if erro:
            self.var_status_busca.set("Tarefa encerrada com erro. Consulte os logs.")
        else:
            self.var_status_busca.set(mensagem_sucesso)

    # --- AÇÕES DOS BOTÕES ---

    def _acao_ingestao(self):
        termo = self.ent_termo.get().strip()
        try:
            meta = int(self.ent_meta.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "A meta de artigos deve ser um número inteiro.")
            return
        if meta < 1:
            messagebox.showerror("Erro", "A meta de artigos deve ser maior que zero.")
            return

        try:
            ano_inicio = int(self.ent_ano_inicio.get().strip())
            ano_fim = int(self.ent_ano_fim.get().strip())
        except ValueError:
            messagebox.showerror("Erro", "Informe anos válidos para o período da pesquisa.")
            return
        if ano_inicio < 1 or ano_fim < ano_inicio or ano_fim > datetime.now().year:
            messagebox.showerror("Erro", "O período de anos informado é inválido.")
            return

        if not termo:
            messagebox.showwarning("Aviso", "Informe um termo para a pesquisa.")
            return
        modo_rotulo = self.var_modo_busca.get()
        modo_busca = "frase" if modo_rotulo == "Frase exata" else "todos"
        somente_acesso_aberto = self.var_somente_oa.get()

        if not self._definir_busca_em_andamento(True):
            return

        def rodar():
            print("=" * 65)
            print(f"BUSCA: {termo} | {modo_rotulo} | {ano_inicio}-{ano_fim} | meta {meta}")
            print("=" * 65)
            artigos = asyncio.run(executar_busca_artigos(
                termo,
                meta_total_artigos=meta,
                faixas_temporais=[(ano_inicio, ano_fim)],
                modo_busca=modo_busca,
                somente_acesso_aberto=somente_acesso_aberto,
            ))
            if artigos:
                exportar_para_csv(artigos, termo_pesquisa=termo)
            else:
                print("Nenhum artigo encontrado pelas fontes consultadas.")

        self._executar_em_thread(
            rodar,
            ao_concluir=lambda erro: self._definir_busca_em_andamento(False, erro),
        )

    def _acao_analise(self):
        def rodar():
            print("=" * 65)
            print("📊 INICIANDO ETAPA 2: ANÁLISE ESTATÍSTICA DO CSV")
            print("=" * 65)
            arq, dados = carregar_csv_mais_recente()
            if dados:
                analisar_dataset(dados)
        
        self._executar_tarefa_com_barra(rodar, "Calculando tendências do CSV...", "Análise de tendências concluída.")

    def _acao_classificar(self):
        def rodar():
            print("=" * 65)
            print("🏷️ INICIANDO ETAPA 3: CLASSIFICAÇÃO DE ÁREAS CIENTÍFICAS")
            print("=" * 65)
            processar_e_exportar_classificacao()

        self._executar_tarefa_com_barra(rodar, "Classificando artigos e resumos...", "Classificação concluída.")

    def _acao_extrair(self):
        def rodar():
            print("=" * 65)
            print("🎯 INICIANDO ETAPA 4: ISOLAMENTO DE ARTIGOS INTERDISCIPLINARES")
            print("=" * 65)
            extrair_artigos_interdisciplinares()

        self._executar_tarefa_com_barra(rodar, "Selecionando artigos interdisciplinares...", "Seleção interdisciplinar concluída.")

    def _acao_minerar(self):
        def rodar():
            print("=" * 65)
            print("🧠 INICIANDO ETAPA 5: MINERAÇÃO DE TERMOS E MODELOS MATEMÁTICOS")
            print("=" * 65)
            minerar_termos_interdisciplinares()

        self._executar_tarefa_com_barra(rodar, "Minerando títulos e resumos...", "Mineração de termos concluída.")

    def _acao_baixar_pdfs(self):
        def rodar():
            print("=" * 65)
            print("ETAPA 6: BUSCA DE PDFs DE ACESSO ABERTO")
            print("=" * 65)
            baixar_pdfs_unpaywall()

        self._executar_tarefa_com_barra(rodar, "Consultando disponibilidade de PDFs OA...", "Consulta de PDFs finalizada.")


if __name__ == "__main__":
    app = AppProjetoFundacao()
    app.mainloop()