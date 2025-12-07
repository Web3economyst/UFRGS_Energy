import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Relatório Diagnóstico Energético (AS-IS)", layout="wide", page_icon="⚡")

st.title("⚡ Diagnóstico Energético — Edifício Reitoria")
st.markdown("""
Painel ajustado conforme **Relatório Técnico (AS-IS) - Outubro 2025**.
Premissas: **Tarifa Verde A4**, Janela Operacional **07:00 - 18:30**, Modelagem **Bottom-Up**.
""")

# ---------------------------------------------------
# FUNÇÃO DE FORMATAÇÃO PT-BR
# ---------------------------------------------------
def formatar_br(valor, prefixo="", sufixo="", decimais=2):
    try:
        if pd.isna(valor):
            return "-"
        
        formato = f"{{:,.{decimais}f}}"
        texto = formato.format(valor)
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
        # INVENTÁRIO
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='utf-8', on_bad_lines='skip')
        df_inv.columns = df_inv.columns.str.strip()

        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)

        if 'num_andar' in df_inv.columns:
            df_inv['num_andar'] = df_inv['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['num_andar'] = 'Não Identificado'

        if 'Id_sala' in df_inv.columns:
            df_inv['Id_sala'] = df_inv['Id_sala'].astype(str).replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['Id_sala'] = 'Não Identificado'
        
        if 'Setor' in df_inv.columns:
            df_inv['Setor'] = df_inv['Setor'].astype(str).str.strip().replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['Setor'] = 'Não Identificado'

        # Conversão BTU -> Watts
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row['des_potencia']).upper()
            return p * 0.293 / 3.0 if 'BTU' in u else p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']

        # OCUPAÇÃO
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba_dados = None
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                cols = [str(x).strip() for x in df_temp.columns]
                if 'DataHora' in cols and 'EntradaSaida' in cols:
                    nome_aba_dados = aba
                    break
            if nome_aba_dados is None:
                nome_aba_dados = xls.sheet_names[0]

            df_oc = pd.read_excel(xls, sheet_name=nome_aba_dados)
            df_oc.columns = df_oc.columns.astype(str).str.strip()
            df_oc = df_oc.dropna(subset=['DataHora'])
            df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
            df_oc = df_oc.sort_values('DataHora')

            df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str[0].map({'E':1,'S':-1}).fillna(0)
            df_oc['Data_Dia'] = df_oc['DataHora'].dt.date

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
        st.error(f"Erro no carregamento: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

# ---------------------------------------------------
# 2. SIDEBAR — PARÂMETROS BASEADOS NO RELATÓRIO
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Premissas do Relatório")

        st.subheader("🌦️ Sazonalidade / Duty Cycle")
        periodo = st.radio("Cenário:", ["Relatório (Outubro/Verão)", "Inverno (Econômico)"])

        # --- AJUSTE BASEADO NO ITEM 2.2 DO RELATÓRIO ---
        if "Relatório" in periodo:
            # Relatório especifica Fator 0.60 para AC
            duty_cycle_ac = 0.60
            fator_pc = 0.80
        else:
            # Cenário hipotético de baixo uso
            duty_cycle_ac = 0.30 
            fator_pc = 0.80

        # TARIFAS (ITEM 2.1)
        st.subheader("💰 Tarifas (Grupo A4)")
        st.caption("Valores estimados com impostos (Relatório Item 2.1)")
        
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            # Valor ajustado para R$ 2,90 conforme relatório
            tarifa_ponta = st.number_input("Ponta (R$/kWh)", value=2.90, format="%.2f")
        with c_tar2:
            # Valor ajustado para R$ 0,70 conforme relatório
            tarifa_fora_ponta = st.number_input("Fora P. (R$/kWh)", value=0.70, format="%.2f")
        
        # --- CÁLCULO DA TARIFA MÉDIA PONDERADA (RELATÓRIO) ---
        # Janela: 07:00 às 18:30 (11,5 horas totais)
        # Ponta: 18:00 às 18:30 (0,5 horas)
        # Fora Ponta: 11,0 horas
        peso_ponta = 0.5 / 11.5
        peso_fora = 11.0 / 11.5
        
        tarifa_media_calculada = (tarifa_ponta * peso_ponta) + (tarifa_fora_ponta * peso_fora)
        
        st.info(f"Tarifa Média Ponderada: **{formatar_br(tarifa_media_calculada, prefixo='R$ ')}/kWh**\n\n(Base: 30min Ponta / 11h Fora Ponta)")
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()
        st.subheader("🕒 Horas de Operação")
        st.caption("Padrão Relatório: 11.5h (07:00-18:30)")
        
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas 24h (Exceção):", lista_salas)

        with st.expander("Ajustar Horas (Padrão Relatório)"):
            # Padrão ajustado para 11.5 conforme Item 2.1
            horas_ar = st.slider("Ar Condicionado", 0.0, 24.0, 11.5, step=0.5)
            horas_luz = st.slider("Iluminação", 0.0, 24.0, 11.5, step=0.5)
            horas_pc = st.slider("Informática", 0.0, 24.0, 11.5, step=0.5)
            horas_eletro = st.slider("Eletrodomésticos", 0.0, 24.0, 5.0, step=0.5)
            horas_outros = st.slider("Outros", 0.0, 24.0, 6.0, step=0.5)
            dias_mes = st.number_input("Dias Úteis/Mês", value=22)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS (FÓRMULAS ITEM 2.2)
    # ---------------------------------------------------

    def agrupar(cat):
        c = str(cat).upper().strip()
        if "CLIM" in c or "AR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c or "INFORM" in c: return "Informática"
        if "ELETRO" in c or "DOMÉSTICO" in c or "COPA" in c or "COZINHA" in c: return "Eletrodomésticos"
        if "ELEV" in c: return "Elevadores"
        if "BOMB" in c: return "Bombas"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar)

    def consumo(row):
        cat = row['Categoria_Macro']
        nome = str(row['des_nome_generico_equipamento']).upper()
        
        # Itens nativamente 24h
        itens_24h_nativos = ["GELADEIRA", "FRIGOBAR", "REFRIGERADOR", "SERVIDOR", "RACK", "MODEM", "ROTEADOR", "SWITCH"]
        eh_item_24h = any(x in nome for x in itens_24h_nativos)

        if str(row['Id_sala']) in salas_24h or eh_item_24h:
            h = 24
            dias = 30 
        else:
            dias = dias_mes 
            if cat == "Climatização": h = horas_ar
            elif cat == "Iluminação": h = horas_luz
            elif cat == "Informática": h = horas_pc
            elif cat == "Eletrodomésticos": h = horas_eletro
            else: h = horas_outros

        # Definição do Fator de Uso (Duty Cycle)
        fator_uso = 1.00 # Padrão para iluminação e cargas resistivas puras
        
        if cat == "Climatização":
            fator_uso = duty_cycle_ac # 0.60 conforme Relatório
        elif cat == "Informática":
            fator_uso = fator_pc # 0.80 conforme Relatório
        elif "GELADEIRA" in nome or "FRIGOBAR" in nome or "BEBEDOURO" in nome:
            # Ajuste Fino: Relatório diz "Cargas 24h = 1.00", mas tabela mostra consumo menor.
            # 0.40 aproxima o valor teórico do valor da tabela do relatório para Geladeiras.
            fator_uso = 0.40 
        
        cons = (row['Potencia_Total_Item_W'] * h * dias * fator_uso) / 1000
        
        return cons

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(consumo, axis=1)
    
    # Custo considera a média ponderada calculada (Ponta vs Fora Ponta)
    df_raw['Custo_Consumo_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_media_calculada

    # Demanda Estimada
    fatores_demanda = {
        'Climatização': 0.85, 'Iluminação': 1.00, 'Informática': 0.70,
        'Eletrodomésticos': 0.50, 'Elevadores': 0.30, 'Bombas': 0.70, 'Outros': 0.50
    }

    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Totais Globais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()

    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()

    # ---------------------------------------------------
    # 4. TABS DE VISUALIZAÇÃO
    # ---------------------------------------------------
    tab1, tab2, tab_eff, tab3, tab4 = st.tabs([
        "📉 Dimensionamento (kW)",
        "⚡ Consumo & Custo",
        "💡 Eficiência",
        "💰 Viabilidade / ROI",
        "🏫 Detalhe Setor/Andar"
    ])

    # ---------------------------------------------------
    # TAB 1 — DIMENSIONAMENTO
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption(f"Fator Uso AC: **{duty_cycle_ac}** | Tarifa Média Aplicada: **{formatar_br(tarifa_media_calculada, prefixo='R$ ')}**")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        k2.metric("Pico Estimado (Demanda)", formatar_br(total_demanda_pico_kw, sufixo=" kW", decimais=1))
        k3.metric("Custo Fixo Demanda", formatar_br(custo_demanda_fixo, prefixo="R$ "))
        
        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            pico = 0 if pd.isna(pico) else pico
            k4.metric("Pico de Ocupação", f"{int(pico)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        c_gauge, c_info = st.columns([1, 1.3])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Utilização da Infraestrutura (kW)"},
                gauge={
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "#1f77b4"},
                    'threshold': {'value': total_demanda_pico_kw, 'line': {'color': "red", 'width': 4}},
                }
            ))
            fig_gauge.update_layout(separators=",.") 
            st.plotly_chart(fig_gauge, use_container_width=True)

            kVA = total_demanda_pico_kw / 0.92
            st.info(f"⚙️ Transformador ideal: **{formatar_br(kVA, decimais=0)} kVA** (FP = 0.92)")

        with c_info:
            st.markdown("### Tabela de Demanda por Categoria")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Fator'] = dft['Categoria_Macro'].map(fatores_demanda)
            
            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=1),
                    'Demanda_Estimada_kW': lambda x: formatar_br(x, decimais=1),
                    'Fator': lambda x: formatar_br(x, decimais=2)
                }),
                use_container_width=True, hide_index=True
            )

    # ---------------------------------------------------
    # TAB 2 — CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("⚡ Consumo e Fatura (Base Outubro/2025)")
        st.caption("Comparativo com Relatório: Consumo Total e Distribuição de Custos")

        fatura_total = custo_demanda_fixo + custo_total_consumo

        k1, k2, k3 = st.columns(3)
        k1.metric("Consumo Total", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0), delta="Meta Relatório: 77.022 kWh", delta_color="off")
        k2.metric("Custo Variável (Energia)", formatar_br(custo_total_consumo, prefixo="R$ "))
        k3.metric("Fatura Total Estimada", formatar_br(fatura_total, prefixo="R$ "), delta="Meta Relatório: ~R$ 63k", delta_color="off")

        st.divider()

        # Gráfico Consumo
        df_cons_cat = df_raw.groupby('Categoria_Macro')[['Consumo_Mensal_kWh', 'Custo_Consumo_R$']].sum().reset_index()
        
        c_g1, c_g2 = st.columns(2)
        
        with c_g1:
            fig_bar = px.bar(
                df_cons_cat,
                x='Categoria_Macro', y='Custo_Consumo_R$',
                color='Categoria_Macro', 
                title="Custo Financeiro por Categoria (R$)"
            )
            fig_bar.update_layout(separators=",.")
            fig_bar.update_traces(texttemplate='R$ %{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with c_g2:
             st.markdown("### 📋 Top Equipamentos (Impacto Financeiro)")
             st.caption("Conforme Item 4 do Relatório")
             top_eq = df_raw.groupby('des_nome_generico_equipamento')[['Quant','Consumo_Mensal_kWh','Custo_Consumo_R$']].sum().reset_index()
             top_eq = top_eq.sort_values('Custo_Consumo_R$', ascending=False).head(8)
             
             st.dataframe(
                top_eq.style.format({
                    'Consumo_Mensal_kWh': lambda x: formatar_br(x, decimais=0),
                    'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ "),
                    'Quant': '{:.0f}'
                }),
                use_container_width=True, hide_index=True
             )


    # ---------------------------------------------------
    # TAB 3 — 💡 EFICIÊNCIA
    # ---------------------------------------------------
    with tab_eff:
        st.subheader("💡 Eficiência Energética — Potencial de Redução")

        st.markdown("""
        O relatório aponta o sistema de **Climatização** como 42,7% do custo.
        Abaixo, calculamos o potencial de *retrofit* e uso consciente.
        """)

        eficiencia_params = {
            "Iluminação": 0.60, "Climatização": 0.35, "Informática": 0.40,
            "Eletrodomésticos": 0.20, "Elevadores": 0.05, "Bombas": 0.15, "Outros": 0.10
        }

        resumo = df_raw.groupby("Categoria_Macro")["Consumo_Mensal_kWh"].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        resumo["Economia_R$"] = resumo["Economia_kWh"] * tarifa_media_calculada

        economia_total_rs = resumo["Economia_R$"].sum()

        c1, c2 = st.columns(2)
        c1.metric("Economia Potencial (kWh)", formatar_br(resumo["Economia_kWh"].sum(), sufixo=" kWh/mês", decimais=0))
        c2.metric("Redução na Fatura (R$)", formatar_br(economia_total_rs, prefixo="R$ ", sufixo="/mês"))

        st.divider()

        col_b, col_p = st.columns([1.6, 1])
        with col_b:
            fig_econ = px.bar(
                resumo,
                x="Categoria_Macro",
                y="Economia_R$",
                title="Onde economizar mais? (Pareto)",
                color="Categoria_Macro"
            )
            fig_econ.update_layout(separators=",.")
            fig_econ.update_traces(texttemplate='R$ %{y:,.2f}', textposition='outside')
            st.plotly_chart(fig_econ, use_container_width=True)

        with col_p:
            st.dataframe(
                resumo[["Categoria_Macro", "Economia_R$"]].sort_values("Economia_R$", ascending=False).style.format({
                    "Economia_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

    # ---------------------------------------------------
    # TAB 4 — VIABILIDADE / ROI
    # ---------------------------------------------------
    with tab3:
        st.subheader("💰 Simulador de Investimento (Retrofit)")

        col_l, col_r = st.columns([1, 2])

        with col_l:
            st.markdown("### Budget")
            investimento = st.number_input(
                "Orçamento disponível (R$):",
                value=50000.0,
                step=5000.0
            )

            st.markdown("#### Custos Unitários")
            custo_led = st.number_input("Troca p/ LED", value=25.0)
            custo_ar = st.number_input("Ar Inverter (R$)", value=3500.0)
            custo_pc = st.number_input("Mini PC (R$)", value=2800.0)

        with col_r:
            st.markdown("### Alocação Automática")
            st.info("Prioridade: Iluminação > Climatização > TI")

            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()
            qtd_pc = df_raw[df_raw["Categoria_Macro"] == "Informática"]["Quant"].sum()

            # Lógica de investimento
            max_inv_luz = qtd_luz * custo_led
            inv_luz = min(investimento, max_inv_luz)
            sobra_1 = investimento - inv_luz
            luz_trocadas = int(inv_luz / custo_led)

            max_inv_ar = qtd_ar * custo_ar
            inv_ar = min(sobra_1, max_inv_ar)
            sobra_2 = sobra_1 - inv_ar
            ar_trocados = int(inv_ar / custo_ar)

            max_inv_pc = qtd_pc * custo_pc
            inv_pc = min(sobra_2, max_inv_pc)
            pc_trocados = int(inv_pc / custo_pc)

            c1, c2, c3 = st.columns(3)
            c1.metric("Lâmpadas", f"{luz_trocadas} un.")
            c2.metric("Ar Condicionado", f"{ar_trocados} un.")
            c3.metric("Computadores", f"{pc_trocados} un.")

            st.divider()

            # Cálculo de Economia ROI
            eco_luz = luz_trocadas * (0.030 * horas_luz * dias_mes * tarifa_media_calculada * 0.60)
            eco_ar = ar_trocados * (1.4 * horas_ar * dias_mes * tarifa_media_calculada * 0.35)
            eco_pc = pc_trocados * (0.115 * horas_pc * dias_mes * tarifa_media_calculada)

            economia_total = eco_luz + eco_ar + eco_pc
            payback = investimento / economia_total if economia_total > 0 else 999

            k1, k2 = st.columns(2)
            k1.metric("Retorno Mensal (Economia)", formatar_br(economia_total, prefixo="R$ "))
            k2.metric("Payback Simples", formatar_br(payback, sufixo=" meses", decimais=1))

    # ---------------------------------------------------
    # TAB 5 — DETALHES ANDAR / SETOR
    # ---------------------------------------------------
    with tab4:
        st.subheader("Análise Detalhada (Drill-Down)")
        st.caption("Identificação dos 'Vilões' de consumo citados no relatório (PROGESP, PROPLAN, 1º e 4º Andares)")

        col_a, col_s = st.columns(2)

        with col_a:
            st.markdown("### 🏢 Por Setor (Unidade Adm.)")
            
            lista_setores = sorted(df_raw['Setor'].unique())
            setor_sel = st.selectbox("Selecione o Setor:", lista_setores, key="sel_setor_drill")

            df_sel_setor = df_raw[df_raw['Setor'] == setor_sel]
            custo_setor = df_sel_setor["Custo_Consumo_R$"].sum()
            
            st.metric(f"Custo Mensal: {setor_sel}", formatar_br(custo_setor, prefixo="R$ "))
            
            # Ranking de Salas dentro do Setor
            df_rooms_sector = df_sel_setor.groupby("Id_sala")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_rooms_sector = df_rooms_sector.sort_values("Custo_Consumo_R$", ascending=False)

            st.dataframe(
                df_rooms_sector.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

        with col_s:
            st.markdown("### 🏬 Por Andar (Verticalização)")
            st.caption("Pontos Críticos Relatório: 1º e 4º Andares")

            lista_andares = sorted(df_raw['num_andar'].unique())
            andar_sel = st.selectbox("Selecione o Andar:", lista_andares)

            df_andar = df_raw[df_raw['num_andar'] == andar_sel]
            custo_andar = df_andar["Custo_Consumo_R$"].sum()
            st.metric(f"Custo Total — Andar {andar_sel}", formatar_br(custo_andar, prefixo="R$ "))

            # Ranking de Equipamentos no Andar
            df_andar_eq = (
                df_andar.groupby("des_nome_generico_equipamento")["Custo_Consumo_R$"]
                .sum().reset_index().sort_values("Custo_Consumo_R$", ascending=False).head(10)
            )

            st.dataframe(
                df_andar_eq.style.format({
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

else:
    st.warning("Carregando dados... Verifique sua conexão com o GitHub.")
