import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia", layout="wide", page_icon="⚡")

st.title("⚡ Eficiência Energética — Prédio da Reitoria")
st.markdown("""
Painel completo para **dimensionamento de demanda**, **consumo**, 
**análise de ocupação**, **eficiência** e **viabilidade econômica**.
""")

# ---------------------------------------------------
# 1. CARREGAMENTO DOS DADOS
# ---------------------------------------------------
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # INVENTÁRIO
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='cp1252', on_bad_lines='skip')
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
        
        # Tratamento da coluna Setor
        if 'Setor' in df_inv.columns:
            df_inv['Setor'] = df_inv['Setor'].astype(str).str.strip().replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['Setor'] = 'Não Identificado'

        # Conversão BTU → Watts
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
# 2. SIDEBAR — PARÂMETROS E SAZONALIDADE
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros do Modelo")

        st.subheader("🌦️ Estação / Sazonalidade")
        periodo = st.radio("Selecione:", ["Verão (Alto Consumo)", "Inverno/Ameno (Baixo Consumo)"])

        tarifa_base = 0.65
        if "Verão" in periodo:
            fator_sazonal_clima = 1.30
            tarifa_sugerida = 0.72
        else:
            fator_sazonal_clima = 0.60
            tarifa_sugerida = 0.58

        st.subheader("💰 Tarifas")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=tarifa_sugerida, format="%.2f")
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()
        st.subheader("🕒 Salas 24h")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Escolha:", lista_salas)

        with st.expander("Horas de Uso por Categoria"):
            horas_ar = st.slider("Ar Condicionado", 0, 24, 8)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_pc = st.slider("Informática", 0, 24, 9)
            horas_eletro = st.slider("Eletrodomésticos", 0, 24, 5)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias no mês", value=22)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS
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

    # Consumo com sazonalidade avançada
    def consumo(row):
        cat = row['Categoria_Macro']
        if str(row['Id_sala']) in salas_24h:
            h = 24
            dias = 30
        else:
            if cat == "Climatização": h = horas_ar
            elif cat == "Iluminação": h = horas_luz
            elif cat == "Informática": h = horas_pc
            elif cat == "Eletrodomésticos": h = horas_eletro
            else: h = horas_outros
            dias = dias_mes

        cons = (row['Potencia_Total_Item_W'] * h * dias) / 1000
        
        if cat == 'Climatização':
            return cons * fator_sazonal_clima
        return cons

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(consumo, axis=1)
    df_raw['Custo_Consumo_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh

    # Demanda
    fatores_demanda = {
        'Climatização': 0.85,
        'Iluminação': 1.00,
        'Informática': 0.70,
        'Eletrodomésticos': 0.50,
        'Elevadores': 0.30,
        'Bombas': 0.70,
        'Outros': 0.50
    }

    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Totais
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
        "⚡ Consumo (kWh)",
        "💡 Eficiência",
        "💰 Viabilidade / ROI",
        "🏫 Detalhe por Andar / Sala"
    ])

    # ---------------------------------------------------
    # TAB 1 — DIMENSIONAMENTO (BLOCO 1)
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption(f"Estação atual: **{periodo}** (Clima: {fator_sazonal_clima}x)")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", f"{total_instalado_kw:,.1f} kW")
        k2.metric("Pico Estimado (Demanda)", f"{total_demanda_pico_kw:,.1f} kW")
        k3.metric("Custo Fixo Demanda", f"R$ {custo_demanda_fixo:,.2f}")

        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            pico = 0 if pd.isna(pico) else pico
            k4.metric("Pico de Ocupação", f"{int(pico)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        if not df_ocupacao.empty:
            st.markdown("### 👥 Ocupação — Fluxo ao longo do tempo")
            fig_oc = px.line(df_ocupacao, x="DataHora", y="Ocupacao_Acumulada",
                             title="Fluxo de Pessoas (Acumulado Diário)")
            st.plotly_chart(fig_oc, use_container_width=True)
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
            st.plotly_chart(fig_gauge, use_container_width=True)

            kVA = total_demanda_pico_kw / 0.92
            st.info(f"⚙️ Transformador recomendado: **{kVA:.0f} kVA** (FP = 0.92)")

        with c_info:
            st.markdown("### Tabela de Demanda por Categoria")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Fator'] = dft['Categoria_Macro'].map(fatores_demanda)
            dft['Custo Demanda (R$)'] = dft['Demanda_Estimada_kW'] * tarifa_kw_demanda

            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': "{:.1f}",
                    'Demanda_Estimada_kW': "{:.1f}",
                    'Fator': "{:.2f}",
                    'Custo Demanda (R$)': "R$ {:.2f}"
                }),
                use_container_width=True, hide_index=True
            )

        st.divider()

        st.markdown("### 🔍 Consumo Real (kWh) vs Capacidade (kW)")

        potencia_media_kw = consumo_total_kwh / 720  

        p1, p2, p3 = st.columns(3)
        p1.metric("Potência Média Real", f"{potencia_media_kw:.1f} kW")
        p2.metric("Uso vs Pico", f"{(potencia_media_kw/total_demanda_pico_kw)*100:.1f}%")
        p3.metric("Uso vs Instalada", f"{(potencia_media_kw/total_instalado_kw)*100:.1f}%")

        if potencia_media_kw < 0.7 * total_demanda_pico_kw:
            st.success("Uso real **bem abaixo do pico**.")
        elif potencia_media_kw < total_demanda_pico_kw:
            st.info("Uso **dentro da capacidade**, mas próximo do limite.")
        else:
            st.warning("⚠️ Uso real **acima do pico** — revise a demanda.")

    # ---------------------------------------------------
    # TAB 2 — CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("⚡ Consumo Mensal (kWh)")

        fatura_total = custo_demanda_fixo + custo_total_consumo

        k1, k2, k3 = st.columns(3)
        k1.metric("Consumo Total", f"{consumo_total_kwh:,.0f} kWh")
        k2.metric("Custo Variável", f"R$ {custo_total_consumo:,.2f}")
        k3.metric("Conta Total Estimada", f"R$ {fatura_total:,.2f}")

        st.divider()

        fig_bar = px.bar(
            df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index(),
            x='Categoria_Macro', y='Consumo_Mensal_kWh',
            color='Categoria_Macro', text_auto='.2s',
            title="Consumo por Categoria"
        )
        st.plotly_chart(fig_bar, use_container_width=True)


    # ---------------------------------------------------
    # TAB 3 — NOVA ABA 💡 EFICIÊNCIA
    # ---------------------------------------------------
    with tab_eff:
        st.subheader("💡 Eficiência Energética — Potencial de Redução (%) e Economia")

        st.markdown("""
Abaixo você encontra um diagnóstico detalhado de **onde estão os maiores desperdícios**,  
quanto pode ser economizado **por categoria**, e qual seria a **economia total mensal**.
""")

        # --------------------------
        # MODELO DE EFICIÊNCIA REAL
        # --------------------------
        eficiencia_params = {
            "Iluminação": 0.60,          # 60% de redução com LED
            "Climatização": 0.35,        # 35% com inverter
            "Informática": 0.40,         # 40% PCs eficientes
            "Eletrodomésticos": 0.20,    # 20% novos
            "Elevadores": 0.05,
            "Bombas": 0.15,
            "Outros": 0.10
        }

        resumo = (
            df_raw
            .groupby("Categoria_Macro")["Consumo_Mensal_kWh"]
            .sum()
            .reset_index()
        )

        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        resumo["Economia_R$"] = resumo["Economia_kWh"] * tarifa_kwh

        economia_total_kwh = resumo["Economia_kWh"].sum()
        economia_total_rs = resumo["Economia_R$"].sum()

        # KPIs
        c1, c2 = st.columns(2)
        c1.metric("Economia Máxima em Energia", f"{economia_total_kwh:,.0f} kWh/mês")
        c2.metric("Economia Máxima em Reais", f"R$ {economia_total_rs:,.2f}/mês")

        st.divider()

        st.markdown("###  Economia por Categoria")
        st.dataframe(
            resumo.sort_values("Economia_R$", ascending=False).style.format({
                "Consumo_Mensal_kWh": "{:,.0f}",
                "Reducao_%": "{:.0%}",
                "Economia_kWh": "{:,.0f}",
                "Economia_R$": "R$ {:,.2f}"
            }),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        col_b, col_p = st.columns([1.6, 1])
        with col_b:
            fig_econ = px.bar(
                resumo,
                x="Categoria_Macro",
                y="Economia_R$",
                text_auto=".2s",
                title="Economia Potencial por Categoria (R$)",
                color="Categoria_Macro"
            )
            st.plotly_chart(fig_econ, use_container_width=True)

        with col_p:
            fig_pie_e = px.pie(
                resumo,
                values="Economia_R$",
                names="Categoria_Macro",
                hole=0.4,
                title="Distribuição da Economia"
            )
            st.plotly_chart(fig_pie_e, use_container_width=True)

    # ---------------------------------------------------
    # TAB 4 — VIABILIDADE / ROI  (COMPLETO)
    # ---------------------------------------------------
    with tab3:
        st.subheader("💰 Simulador de Viabilidade — ROI do Projeto")

        col_l, col_r = st.columns([1, 2])

        # ------------------------------
        # PARÂMETROS DE INVESTIMENTO
        # ------------------------------
        with col_l:
            st.markdown("### Parâmetros do Projeto")

            investimento = st.number_input(
                "Orçamento disponível (R$):",
                value=50000.0,
                step=5000.0
            )

            st.markdown("#### 🔧 Custos unitários de modernização")
            custo_led = st.number_input("Troca p/ LED", value=25.0)
            custo_ar = st.number_input("Ar Inverter (R$)", value=3500.0)
            custo_pc = st.number_input("Mini PC (R$)", value=2800.0)

            st.info("""
            📌 **Ordem de prioridade automática:** 1) Iluminação → 2) Climatização → 3) Informática  
            """)

        # ------------------------------
        # ALOCAÇÃO OTIMIZADA DA VERBA
        # ------------------------------
        with col_r:
            st.markdown("### Distribuição automática da verba")

            # Quantidades existentes no inventário
            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()
            qtd_pc = df_raw[df_raw["Categoria_Macro"] == "Informática"]["Quant"].sum()

            # --- Aplicação automática da verba ---

            # 1) LED
            max_inv_luz = qtd_luz * custo_led
            inv_luz = min(investimento, max_inv_luz)
            sobra_1 = investimento - inv_luz
            luz_trocadas = int(inv_luz / custo_led)

            # 2) Ar inverter
            max_inv_ar = qtd_ar * custo_ar
            inv_ar = min(sobra_1, max_inv_ar)
            sobra_2 = sobra_1 - inv_ar
            ar_trocados = int(inv_ar / custo_ar)

            # 3) Mini PCs
            max_inv_pc = qtd_pc * custo_pc
            inv_pc = min(sobra_2, max_inv_pc)
            pc_trocados = int(inv_pc / custo_pc)

            # ------------------------------
            # RENDERIZAÇÃO DOS RESULTADOS
            # ------------------------------
            c1, c2, c3 = st.columns(3)
            c1.metric("Lâmpadas instaladas", f"{luz_trocadas} un.")
            c2.metric("Ar-condicionados novos", f"{ar_trocados} un.")
            c3.metric("Mini PCs adquiridos", f"{pc_trocados} un.")

        st.divider()

        # ------------------------------
        # ECONOMIA ESTIMADA (REAL)
        # ------------------------------
        st.markdown("### 📉 Economia Mensal Estimada")

        # Iluminação — economia de 60%
        eco_luz = luz_trocadas * (0.030 * horas_luz * dias_mes * tarifa_kwh * 0.60)

        # Ar Inverter — diferença média 1.4 kW -> 0.9 kW
        eco_ar = ar_trocados * (1.4 * horas_ar * dias_mes * tarifa_kwh * 0.35)

        # PCs — economia típica de 115W
        eco_pc = pc_trocados * (0.115 * horas_pc * dias_mes * tarifa_kwh)

        economia_total = eco_luz + eco_ar + eco_pc
        payback = investimento / economia_total if economia_total > 0 else 999

        k1, k2 = st.columns(2)
        k1.metric("Economia Mensal", f"R$ {economia_total:,.2f}")
        k2.metric("Payback Estimado", f"{payback:.1f} meses")

        if payback < 12:
            st.success("🔋 Excelente viabilidade — retorno inferior a 1 ano.")
        elif payback < 36:
            st.info("Boa viabilidade — retorno moderado.")
        else:
            st.warning("Retorno longo — investimento pouco atrativo.")


    # ---------------------------------------------------
    # TAB 5 — DETALHES ANDAR / SALA
    # ---------------------------------------------------
    with tab4:
        st.subheader("Análise detalhada")

        col_a, col_s = st.columns(2)

        # ---------------------------
        # ANÁLISE POR ANDAR
        # ---------------------------
        with col_a:
            st.markdown("### 🏬 Andares")

            # Média de aparelhos por andar (GLOBAL)
            qtd_por_andar = df_raw.groupby('num_andar')['Quant'].sum()
            media_aparelhos = qtd_por_andar.mean()
            st.metric("Média de Aparelhos por Andar", f"{media_aparelhos:,.0f} un.")

            lista_andares = sorted(df_raw['num_andar'].unique())
            andar_sel = st.selectbox("Selecione o andar:", lista_andares)

            df_andar = df_raw[df_raw['num_andar'] == andar_sel]

            custo_andar = df_andar["Custo_Consumo_R$"].sum()
            st.metric(f"Custo Total — Andar {andar_sel}", f"R$ {custo_andar:,.2f}")

            df_andar_salas = (
                df_andar.groupby("Id_sala")["Custo_Consumo_R$"]
                .sum()
                .reset_index()
                .sort_values("Custo_Consumo_R$", ascending=False)
            )

            st.dataframe(
                df_andar_salas,
                use_container_width=True,
                hide_index=True
            )

        # ---------------------------
        # ANÁLISE POR SALA
        # ---------------------------
        with col_s:
            st.markdown("### 🚪 Salas")

            lista_salas = sorted(df_raw['Id_sala'].unique())
            sala_sel = st.selectbox("Selecione a sala:", lista_salas)

            df_sala = df_raw[df_raw['Id_sala'] == sala_sel]

            custo_sala = df_sala["Custo_Consumo_R$"].sum()
            st.metric(f"Custo Total — Sala {sala_sel}", f"R$ {custo_sala:,.2f}")

            st.dataframe(
                df_sala[
                    ["des_nome_equipamento", "Quant", "Potencia_Instalada_kW", "Custo_Consumo_R$"]
                ].sort_values("Custo_Consumo_R$", ascending=False),
                use_container_width=True,
                hide_index=True
            )
        
        st.divider()

        # ---------------------------
        # CONSUMO POR SETOR
        # ---------------------------
        st.markdown("### 🏢 Consumo por Setor (Unidade Administrativa)")
        
        # <--- NOVA MÉTRICA ADICIONADA: MÉDIA POR SETOR --->
        qtd_por_setor = df_raw.groupby('Setor')['Quant'].sum()
        media_aparelhos_setor = qtd_por_setor.mean()
        st.metric("Média de Aparelhos por Unidade Adm.", f"{media_aparelhos_setor:,.0f} un.")
        # <------------------------------------------------>

        df_setor = df_raw.groupby("Setor")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
        df_setor = df_setor.sort_values("Custo_Consumo_R$", ascending=False)
        
        st.dataframe(
            df_setor.style.format({
                "Consumo_Mensal_kWh": "{:,.0f} kWh",
                "Custo_Consumo_R$": "R$ {:,.2f}"
            }),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        # ---------------------------
        # GASTOS APARELHOS TÉRMICOS / COZINHA (LISTA ESPECÍFICA)
        # ---------------------------
        st.markdown("### 🔥❄️ Gasto Relacionado a Aparelhos Térmicos e de Cozinha")
        st.caption("Filtro: Ar Condicionado, Geladeira, Frigobar, Bebedouro, Microondas, Cafeteira, etc.")
        
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
            c_clim1.metric("Custo Total (Selecionados)", f"R$ {df_clim['Custo_Consumo_R$'].sum():,.2f}")
            c_clim2.metric("Consumo Total (Selecionados)", f"{df_clim['Consumo_Mensal_kWh'].sum():,.0f} kWh")

            st.dataframe(
                df_clim_g.style.format({
                    "Consumo_Mensal_kWh": "{:,.0f} kWh",
                    "Custo_Consumo_R$": "R$ {:,.2f}"
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nenhum equipamento da lista específica foi identificado.")

else:
    st.warning("Carregando dados... Verifique sua conexão.")
