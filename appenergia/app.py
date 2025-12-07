import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia", layout="wide", page_icon="⚡")

st.title("⚡ Eficiência Energética — Prédio da Reitoria (Diagnóstico As-Is)")
st.markdown("""
Painel de controle alinhado ao **Relatório Técnico de Outubro/2025**.
Este dashboard estabelece a linha de base ("Baseline") cruzando o inventário físico com o perfil de ocupação e tarifário real.

**Metodologia:** "Bottom-Up" (Custo reconstruído item a item).
""")

# ---------------------------------------------------
# FUNÇÃO DE FORMATAÇÃO PT-BR
# ---------------------------------------------------
def formatar_br(valor, prefixo="", sufixo="", decimais=2):
    """
    Formata números float para string no padrão brasileiro:
    1.234,56 (milhar com ponto, decimal com vírgula)
    """
    try:
        if pd.isna(valor):
            return "-"
        
        # Formata primeiro com padrão US
        formato = f"{{:,.{decimais}f}}"
        texto = formato.format(valor)
        
        # Troca os caracteres para BR
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
        
        return f"{prefixo}{texto}{sufixo}"
    except Exception:
        return str(valor)

# ---------------------------------------------------
# 1. CARREGAMENTO DOS DADOS
# ---------------------------------------------------
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/refs/heads/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # --- CARREGAMENTO DO INVENTÁRIO ---
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='utf-8', on_bad_lines='skip')
        df_inv.columns = df_inv.columns.str.strip()

        # Tratamento de nulos numéricos
        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)

        # Tratamento de strings (Setor, Andar, Sala)
        for col in ['num_andar', 'Id_sala', 'Setor']:
            if col in df_inv.columns:
                df_inv[col] = df_inv[col].astype(str).str.strip().replace(['nan','NaN','', 'nan.0'], 'Não Identificado')
                # Remove o .0 de andares se existir
                if col == 'num_andar':
                    df_inv[col] = df_inv[col].str.replace(r'\.0$', '', regex=True)
            else:
                df_inv[col] = 'Não Identificado'

        # Conversão BTU -> Watts (Mantendo lógica original do seu código)
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row['des_potencia']).upper()
            return p * 0.293 / 3.0 if 'BTU' in u else p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']

        # --- CARREGAMENTO DA OCUPAÇÃO ---
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba_dados = xls.sheet_names[0]
            
            df_oc = pd.read_excel(xls, sheet_name=nome_aba_dados)
            df_oc.columns = df_oc.columns.astype(str).str.strip()
            df_oc = df_oc.dropna(subset=['DataHora'])
            df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
            df_oc = df_oc.sort_values('DataHora')

            # Criação da variação (+1 entra, -1 sai)
            df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str[0].map({'E':1,'S':-1}).fillna(0)
            df_oc['Data_Dia'] = df_oc['DataHora'].dt.date

            # Ajuste de saldo diário (evitar ocupação negativa)
            def ajustar_dia(grupo):
                grupo = grupo.sort_values('DataHora')
                grupo['Ocupacao_Dia'] = grupo['Variacao'].cumsum()
                m = grupo['Ocupacao_Dia'].min()
                if m < 0: grupo['Ocupacao_Dia'] += abs(m)
                return grupo

            df_oc = df_oc.groupby('Data_Dia', group_keys=False).apply(ajustar_dia)
            df_oc['Ocupacao_Acumulada'] = df_oc['Ocupacao_Dia']

        except Exception:
            df_oc = pd.DataFrame()

        return df_inv, df_oc

    except Exception as e:
        st.error(f"Erro crítico no carregamento: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

# ---------------------------------------------------
# 2. SIDEBAR — PARÂMETROS E TARIFAS (AJUSTE TÉCNICO)
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros do Relatório")

        # --- TARIFAS GRUPO A4 VERDE ---
        st.subheader("💰 Tarifas (R$/kWh)")
        st.caption("Base: Outubro/2025 (Com impostos estimados)")
        
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            tarifa_ponta = st.number_input("Ponta (18h-21h)", value=2.90, format="%.2f", help="Valor cheio com impostos")
        with c_tar2:
            tarifa_fora_ponta = st.number_input("Fora Ponta", value=0.70, format="%.2f", help="Valor cheio com impostos")
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()

        # --- OPERAÇÃO ---
        st.subheader("🕒 Regime Operacional")
        dias_mes = st.number_input("Dias Úteis / Mês", value=22, help="Padrão dias úteis comerciais")
        
        # Definição Exata do Relatório:
        # Janela: 07:00 as 18:30 (11,5 horas totais)
        # Invasão Ponta: 18:00 as 18:30 (0,5 horas)
        
        horas_expediente_total = 11.5
        horas_expediente_ponta = 0.5 
        horas_expediente_fora = horas_expediente_total - horas_expediente_ponta

        # Definição Cargas 24h (Servidores, Geladeiras):
        # 3h na ponta (18h-21h) + 21h fora de ponta
        horas_24h_ponta = 3.0
        horas_24h_fora = 21.0

        # --- CÁLCULO AUTOMÁTICO DO CUSTO MÉDIO (MIX) ---
        # Mix 1: Para quem trabalha no horário de expediente
        custo_kwh_expediente = ((horas_expediente_fora * tarifa_fora_ponta) + (horas_expediente_ponta * tarifa_ponta)) / horas_expediente_total
        
        # Mix 2: Para equipamentos ligados direto (24h)
        custo_kwh_24h = ((horas_24h_fora * tarifa_fora_ponta) + (horas_24h_ponta * tarifa_ponta)) / 24.0

        # Mostra o cálculo para o usuário validar
        st.info(f"**Tarifa Média (Expediente):** {formatar_br(custo_kwh_expediente, prefixo='R$ ')}")
        st.caption("Considera mix: 11h Fora + 30min Ponta")
        
        st.info(f"**Tarifa Média (24h):** {formatar_br(custo_kwh_24h, prefixo='R$ ')}")
        st.caption("Considera mix: 21h Fora + 3h Ponta")

        with st.expander("Detalhes dos Fatores de Uso"):
            st.markdown("""
            * **Ar Condicionado:** 0.60 (Ciclo compressor)
            * **Computadores:** 0.80 (Ociosidade)
            * **Iluminação:** 1.00 (Constante)
            * **Cargas 24h:** 1.00 (Ininterrupto)
            """)

    # ---------------------------------------------------
    # 3. MOTOR DE CÁLCULO (AJUSTADO AO RELATÓRIO)
    # ---------------------------------------------------

    # Agrupamento Macro
    def agrupar(cat):
        c = str(cat).upper().strip()
        if "CLIM" in c or "AR" in c or "VENTILADOR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c or "INFORM" in c or "PC" in c or "NOTEBOOK" in c: return "Informática"
        if "ELETRO" in c or "DOMÉSTICO" in c or "COPA" in c or "COZINHA" in c or "GELADEIRA" in c or "CAFETEIRA" in c: return "Eletrodomésticos"
        if "ELEV" in c: return "Elevadores"
        if "BOMB" in c: return "Bombas"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar)

    # Identificação de Cargas 24h (Keywords críticas do relatório)
    def is_always_on(equip_name):
        n = str(equip_name).upper()
        keywords_24h = ["GELADEIRA", "FREEZER", "FRIGOBAR", "SERVIDOR", "RACK", "NOBREAK", "BEBEDOURO", "REFRIGERADOR"]
        return any(k in n for k in keywords_24h)

    # Função Mestra de Consumo
    def calcular_metricas_detalhadas(row):
        cat = row['Categoria_Macro']
        nome = row['des_nome_generico_equipamento']
        potencia_w = row['Potencia_Total_Item_W']
        
        # Lógica de Horário e Tarifa
        eh_24h = is_always_on(nome)

        if eh_24h:
            horas_dia = 24.0
            dias_calculo = 30   # Cargas 24h rodam 30 dias
            fator_uso = 1.0     # Sem ciclo de desligamento
            custo_kwh_aplicavel = custo_kwh_24h
        else:
            horas_dia = horas_expediente_total # 11.5h
            dias_calculo = dias_mes            # 22 dias úteis
            custo_kwh_aplicavel = custo_kwh_expediente
            
            # Fatores de Uso (Duty Cycle) do Relatório
            if cat == "Climatização":
                fator_uso = 0.60 
            elif cat == "Informática":
                fator_uso = 0.80 
            elif cat == "Iluminação":
                fator_uso = 1.00 
            else:
                fator_uso = 0.50 

        # Cálculo kWh Mensal
        consumo_kwh = (potencia_w * horas_dia * dias_calculo * fator_uso) / 1000.0
        
        # Cálculo Custo (R$)
        custo_rs = consumo_kwh * custo_kwh_aplicavel

        return pd.Series([consumo_kwh, custo_rs, fator_uso])

    # Aplica o cálculo linha a linha
    df_raw[['Consumo_Mensal_kWh', 'Custo_Consumo_R$', 'Fator_Uso_Aplicado']] = df_raw.apply(calcular_metricas_detalhadas, axis=1)

    # Demanda Estimada (Pico Instantâneo)
    # Fatores de simultaneidade para pico (diferente do consumo mensal)
    fatores_demanda = {
        'Climatização': 0.70, 'Iluminação': 1.00, 'Informática': 0.70,
        'Eletrodomésticos': 0.50, 'Elevadores': 0.30, 'Bombas': 0.70, 'Outros': 0.50
    }

    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Consolidação dos Totais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
    fatura_total = custo_demanda_fixo + custo_total_consumo

    # ---------------------------------------------------
    # 4. DASHBOARD - VISUALIZAÇÃO
    # ---------------------------------------------------
    
    # Abas conforme estrutura original
    tab1, tab2, tab_eff, tab3, tab4 = st.tabs([
        "📉 Dimensionamento (kW)",
        "⚡ Consumo (kWh)",
        "💡 Eficiência",
        "💰 Viabilidade / ROI",
        "🏫 Detalhe por Andar / Sala"
    ])

    # --- TAB 1: DIMENSIONAMENTO ---
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption("Considerando simultaneidade típica para edifícios administrativos.")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        k2.metric("Pico Estimado (Demanda)", formatar_br(total_demanda_pico_kw, sufixo=" kW", decimais=1))
        k3.metric("Custo Fixo Demanda", formatar_br(custo_demanda_fixo, prefixo="R$ "))
        
        if not df_ocupacao.empty:
            pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
            pico_pessoas = 0 if pd.isna(pico_pessoas) else pico_pessoas
            k4.metric("Pico de Ocupação", f"{int(pico_pessoas)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        # Gráfico de Linha da Ocupação (Se existir)
        if not df_ocupacao.empty:
            st.markdown("### 👥 Fluxo de Pessoas")
            fig_oc = px.line(df_ocupacao, x="DataHora", y="Ocupacao_Acumulada", title="Fluxo Acumulado")
            fig_oc.update_layout(separators=",.") 
            st.plotly_chart(fig_oc, use_container_width=True)
            st.divider()

        # Gauge Chart + Tabela de Demanda
        c_gauge, c_info = st.columns([1, 1.3])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Uso da Infraestrutura (kW)"},
                gauge={
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "#1f77b4"},
                    'threshold': {'value': total_demanda_pico_kw, 'line': {'color': "red", 'width': 4}},
                }
            ))
            fig_gauge.update_layout(separators=",.") 
            st.plotly_chart(fig_gauge, use_container_width=True)

            kVA = total_demanda_pico_kw / 0.92
            st.info(f"⚙️ Transformador sugerido: **{formatar_br(kVA, decimais=0)} kVA** (FP = 0.92)")

        with c_info:
            st.markdown("### Demanda por Categoria")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Custo Demanda (R$)'] = dft['Demanda_Estimada_kW'] * tarifa_kw_demanda

            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=1),
                    'Demanda_Estimada_kW': lambda x: formatar_br(x, decimais=1),
                    'Custo Demanda (R$)': lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

        st.divider()
        
        # Comparativo Potência Média vs Pico
        potencia_media_kw = consumo_total_kwh / 720 # Média flat 24h
        p1, p2, p3 = st.columns(3)
        p1.metric("Potência Média (Flat)", formatar_br(potencia_media_kw, sufixo=" kW", decimais=1))
        p2.metric("Uso vs Pico", formatar_br((potencia_media_kw/total_demanda_pico_kw)*100, sufixo="%"))
        p3.metric("Fator de Carga", formatar_br((potencia_media_kw/total_instalado_kw)*100, sufixo="%"))
        
        if potencia_media_kw < 0.35 * total_demanda_pico_kw:
             st.warning("⚠️ Fator de carga baixo (0,32 est.). Picos altos e consumo médio baixo.")

    # --- TAB 2: CONSUMO ---
    with tab2:
        st.subheader("⚡ Consumo Mensal e Fatura Sombra")

        k1, k2, k3 = st.columns(3)
        k1.metric("Consumo Total", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0))
        k2.metric("Custo Variável (Energia)", formatar_br(custo_total_consumo, prefixo="R$ "))
        k3.metric("Fatura Total Estimada", formatar_br(fatura_total, prefixo="R$ "))

        st.divider()

        df_cons_cat = df_raw.groupby('Categoria_Macro')[['Consumo_Mensal_kWh', 'Custo_Consumo_R$']].sum().reset_index()
        
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            fig_bar = px.bar(
                df_cons_cat,
                x='Categoria_Macro', y='Consumo_Mensal_kWh',
                color='Categoria_Macro', 
                title="Consumo por Categoria (kWh)"
            )
            fig_bar.update_layout(separators=",.")
            fig_bar.update_traces(texttemplate='%{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with col_g2:
            fig_pie = px.pie(
                df_cons_cat,
                values='Custo_Consumo_R$',
                names='Categoria_Macro',
                hole=0.4,
                title="Distribuição do Custo (R$)"
            )
            fig_pie.update_layout(separators=",.")
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- TAB 3: EFICIÊNCIA ---
    with tab_eff:
        st.subheader("💡 Potencial de Eficiência Energética")
        st.markdown("Diagnóstico detalhado de oportunidades de redução baseados em retrofit e boas práticas.")

        eficiencia_params = {
            "Iluminação": 0.60, "Climatização": 0.35, "Informática": 0.40,
            "Eletrodomésticos": 0.20, "Elevadores": 0.05, "Bombas": 0.15, "Outros": 0.10
        }

        resumo = df_raw.groupby("Categoria_Macro")["Consumo_Mensal_kWh"].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        # Aplica a tarifa média de expediente para estimar a economia financeira (conservador)
        resumo["Economia_R$"] = resumo["Economia_kWh"] * custo_kwh_expediente

        economia_total_kwh = resumo["Economia_kWh"].sum()
        economia_total_rs = resumo["Economia_R$"].sum()

        c1, c2 = st.columns(2)
        c1.metric("Economia Energia", formatar_br(economia_total_kwh, sufixo=" kWh/mês", decimais=0))
        c2.metric("Economia Financeira", formatar_br(economia_total_rs, prefixo="R$ ", sufixo="/mês"))

        st.divider()

        st.markdown("### Tabela de Oportunidades")
        st.dataframe(
            resumo.sort_values("Economia_R$", ascending=False).style.format({
                "Consumo_Mensal_kWh": lambda x: formatar_br(x, decimais=0),
                "Reducao_%": "{:.0%}",
                "Economia_kWh": lambda x: formatar_br(x, decimais=0),
                "Economia_R$": lambda x: formatar_br(x, prefixo="R$ ")
            }),
            use_container_width=True, hide_index=True
        )

        st.divider()
        
        # Gráficos de Eficiência
        c_e1, c_e2 = st.columns([1.6, 1])
        with c_e1:
            fig_econ = px.bar(
                resumo, x="Categoria_Macro", y="Economia_R$", title="Potencial Financeiro (R$)", color="Categoria_Macro"
            )
            fig_econ.update_layout(separators=",.")
            fig_econ.update_traces(texttemplate='R$ %{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_econ, use_container_width=True)

    # --- TAB 4: VIABILIDADE / ROI ---
    with tab3:
        st.subheader("💰 Simulador de Investimento e ROI")

        col_l, col_r = st.columns([1, 2])

        with col_l:
            st.markdown("### Inputs do Projeto")
            investimento = st.number_input("Orçamento Disponível (R$):", value=50000.0, step=5000.0)

            st.markdown("#### Custos de Modernização")
            custo_led = st.number_input("Troca LED (Unitário)", value=25.0)
            custo_ar = st.number_input("Ar Inverter (Unitário)", value=3500.0)
            custo_pc = st.number_input("Mini PC (Unitário)", value=2800.0)

            st.info("Prioridade: 1) Luz → 2) Clima → 3) TI")

        with col_r:
            st.markdown("### Alocação Automática de Recursos")

            # Contagens
            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()
            qtd_pc = df_raw[df_raw["Categoria_Macro"] == "Informática"]["Quant"].sum()

            # Lógica de distribuição de verba
            inv_luz = min(investimento, qtd_luz * custo_led)
            luz_trocadas = int(inv_luz / custo_led) if custo_led > 0 else 0
            
            sobra_1 = investimento - inv_luz
            inv_ar = min(sobra_1, qtd_ar * custo_ar)
            ar_trocados = int(inv_ar / custo_ar) if custo_ar > 0 else 0
            
            sobra_2 = sobra_1 - inv_ar
            inv_pc = min(sobra_2, qtd_pc * custo_pc)
            pc_trocados = int(inv_pc / custo_pc) if custo_pc > 0 else 0

            # Exibição
            c1, c2, c3 = st.columns(3)
            c1.metric("Lâmpadas Novas", formatar_br(luz_trocadas, sufixo=" un.", decimais=0))
            c2.metric("Ar-Condicionados Novos", formatar_br(ar_trocados, sufixo=" un.", decimais=0))
            c3.metric("PCs Novos", formatar_br(pc_trocados, sufixo=" un.", decimais=0))

        st.divider()

        st.markdown("### 📉 Retorno Financeiro")
        
        # Cálculo de Economia gerada pelos itens novos
        # Usa custo_kwh_expediente como base
        eco_luz = luz_trocadas * (0.030 * horas_expediente_total * dias_mes * custo_kwh_expediente * 0.60)
        eco_ar = ar_trocados * (1.4 * horas_expediente_total * dias_mes * custo_kwh_expediente * 0.35)
        eco_pc = pc_trocados * (0.115 * horas_expediente_total * dias_mes * custo_kwh_expediente)

        economia_total_proj = eco_luz + eco_ar + eco_pc
        payback = investimento / economia_total_proj if economia_total_proj > 0 else 999

        k1, k2 = st.columns(2)
        k1.metric("Economia Mensal Gerada", formatar_br(economia_total_proj, prefixo="R$ "))
        k2.metric("Payback Estimado", formatar_br(payback, sufixo=" meses", decimais=1))

        if payback < 12:
            st.success("✅ Retorno Excelente (< 1 ano)")
        elif payback < 36:
            st.info("ℹ️ Retorno Moderado (1 a 3 anos)")
        else:
            st.warning("⚠️ Retorno Longo (> 3 anos)")

    # --- TAB 5: DETALHAMENTO (DRILL-DOWN) ---
    with tab4:
        st.subheader("Análise Detalhada (Drill-Down)")

        col_a, col_s = st.columns(2)

        # BLOCO SETOR (Esquerda)
        with col_a:
            st.markdown("### 🏢 Consumo por Setor (Unidade Adm.)")
            
            # Estatística rápida
            qtd_por_setor = df_raw.groupby('Setor')['Quant'].sum()
            st.metric("Média de Itens/Setor", formatar_br(qtd_por_setor.mean(), sufixo=" un.", decimais=0))

            # Seletor
            lista_setores = sorted(df_raw['Setor'].unique())
            setor_sel = st.selectbox("Selecione a Unidade:", lista_setores, key="sel_setor_drill")

            # Filtro
            df_sel_setor = df_raw[df_raw['Setor'] == setor_sel]
            
            custo_setor = df_sel_setor["Custo_Consumo_R$"].sum()
            consumo_setor = df_sel_setor["Consumo_Mensal_kWh"].sum()
            
            c_s1, c_s2 = st.columns(2)
            c_s1.metric("Custo Setor", formatar_br(custo_setor, prefixo="R$ "))
            c_s2.metric("Consumo Setor", formatar_br(consumo_setor, sufixo=" kWh", decimais=0))

            st.caption(f"Salas vinculadas ao setor: **{setor_sel}**")
            
            # Tabela Agrupada por Sala
            df_rooms_sector = df_sel_setor.groupby("Id_sala")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_rooms_sector = df_rooms_sector.sort_values("Custo_Consumo_R$", ascending=False)

            st.dataframe(
                df_rooms_sector.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

            st.divider()

            # Ranking Geral
            with st.expander("📊 Ver Ranking Geral de Setores"):
                df_setor_all = df_raw.groupby("Setor")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
                df_setor_all = df_setor_all.sort_values("Custo_Consumo_R$", ascending=False)
                st.dataframe(
                    df_setor_all.style.format({
                        "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                        "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                    }),
                    use_container_width=True, hide_index=True
                )

        # BLOCO SALA INDIVIDUAL (Direita)
        with col_s:
            st.markdown("### 🚪 Consulta Específica por Sala")

            lista_salas = sorted(df_raw['Id_sala'].unique())
            sala_sel = st.selectbox("Selecione a sala:", lista_salas)

            df_sala = df_raw[df_raw['Id_sala'] == sala_sel]
            custo_sala = df_sala["Custo_Consumo_R$"].sum()
            st.metric(f"Custo Total — Sala {sala_sel}", formatar_br(custo_sala, prefixo="R$ "))

            # Detalhe dos equipamentos na sala
            st.dataframe(
                df_sala[["des_nome_equipamento", "Quant", "Potencia_Instalada_kW", "Custo_Consumo_R$"]]
                .sort_values("Custo_Consumo_R$", ascending=False)
                .style.format({
                    "Quant": lambda x: formatar_br(x, decimais=0),
                    "Potencia_Instalada_kW": lambda x: formatar_br(x, decimais=3),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )
        
        st.divider()

        # BLOCO ANDAR (Largo)
        st.markdown("### 🏬 Análise Vertical (Andares)")

        lista_andares = sorted(df_raw['num_andar'].unique())
        andar_sel = st.selectbox("Selecione o andar:", lista_andares)

        df_andar = df_raw[df_raw['num_andar'] == andar_sel]
        custo_andar = df_andar["Custo_Consumo_R$"].sum()
        st.metric(f"Custo Total — Andar {andar_sel}", formatar_br(custo_andar, prefixo="R$ "))

        df_andar_salas = (
            df_andar.groupby("Id_sala")["Custo_Consumo_R$"]
            .sum().reset_index().sort_values("Custo_Consumo_R$", ascending=False)
        )

        st.dataframe(
            df_andar_salas.style.format({
                "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
            }),
            use_container_width=True, hide_index=True
        )

        st.divider()

        # BLOCO EQUIPAMENTOS ESPECÍFICOS (Térmicos/Copa)
        st.markdown("### 🔥❄️ Filtro: Equipamentos Térmicos e de Copa")
        st.caption("Foco: Ar Condicionado, Geladeira, Microondas, Cafeteiras, etc.")
        
        target_keywords = [
            "AR CONDICIONADO", "GELADEIRA", "FRIGOBAR", "REFRIGERADOR", 
            "BEBEDOURO", "DESUMIDIFICADOR", "VENTILADOR", "MICROONDAS", 
            "TORRADEIRA", "CAFETEIRA", "CHALEIRA", "FOGÃO", "FORNO", 
            "AQUECEDOR", "FOGAREIRO"
        ]
        
        def is_target_appliance(nome):
            n = str(nome).upper()
            return any(k in n for k in target_keywords)
        
        df_clim = df_raw[df_raw['des_nome_generico_equipamento'].apply(is_target_appliance)].copy()
        
        if not df_clim.empty:
            df_clim_g = df_clim.groupby("des_nome_generico_equipamento")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_clim_g = df_clim_g.sort_values("Custo_Consumo_R$", ascending=False)
            
            c_clim1, c_clim2 = st.columns(2)
            c_clim1.metric("Custo Total (Selecionados)", formatar_br(df_clim['Custo_Consumo_R$'].sum(), prefixo="R$ "))
            c_clim2.metric("Consumo Total (Selecionados)", formatar_br(df_clim['Consumo_Mensal_kWh'].sum(), sufixo=" kWh", decimais=0))

            st.dataframe(
                df_clim_g.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Nenhum equipamento da lista específica foi identificado.")

else:
    st.warning("Carregando dados... Verifique sua conexão.")
