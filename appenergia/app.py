import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia (Dimensionamento)", layout="wide", page_icon="⚡")

st.title("⚡ Gestão de Energia — Dimensionamento e Consumo")
st.markdown("""
Painel completo para **dimensionamento de demanda**, **consumo**, 
**análise de ocupação**, **eficiência** e **viabilidade econômica**.

Inclui:
- Cálculo realista com **sazonalidade avançada**  
- Comparação entre **Pico de Demanda (kW)** e **Uso Real (kWh)**  
- Transformador recomendado  
- Dimensionamento de salas e andares  
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
        c = str(cat).upper()
        if "CLIM" in c or "AR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c: return "Informática"
        if "ELETRO" in c: return "Eletrodomésticos"
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
    tab1, tab2, tab3, tab4 = st.tabs([
        "📉 Dimensionamento (kW)",
        "⚡ Consumo (kWh)",
        "💡 Viabilidade / ROI",
        "🏫 Detalhe por Andar / Sala"
    ])

    # ---------------------------------------------------
    # TAB 1 — DIMENSIONAMENTO (BLOCO 1)
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption(f"Estação atual: **{periodo}** (Clima: {fator_sazonal_clima}x)")

        # BLOCO 1 — KPIs PRINCIPAIS
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", f"{total_instalado_kw:,.1f} kW")
        k2.metric("Pico Estimado (Demanda)", f"{total_demanda_pico_kw:,.1f} kW")
        k3.metric("Custo Fixo Demanda", f"R$ {custo_demanda_fixo:,.2f}")

        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            if pd.isna(pico): pico = 0
            k4.metric("Pico de Ocupação", f"{int(pico)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        # Gráfico de Ocupação
        if not df_ocupacao.empty:
            st.markdown("### 👥 Ocupação — Fluxo ao longo do tempo")
            fig_oc = px.line(df_ocupacao, x="DataHora", y="Ocupacao_Acumulada",
                             title="Fluxo de Pessoas (Acumulado Diário)")
            st.plotly_chart(fig_oc, use_container_width=True)
            st.divider()

        # Gauge
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

            # Transformador
            kVA = total_demanda_pico_kw / 0.92
            st.info(f"⚙️ Transformador recomendado: **{kVA:.0f} kVA** (FP = 0.92)")
        
        # Tabela de Demanda
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

        # Comparação kW médio vs kW pico
        st.markdown("### 🔍 Comparação Automática: Consumo Real (kWh) vs Capacidade (kW)")

        potencia_media_kw = consumo_total_kwh / 720  # 30 dias * 24h

        p1, p2, p3 = st.columns(3)
        p1.metric("Potência Média Real", f"{potencia_media_kw:.1f} kW")
        p2.metric("Uso vs Pico Estimado", f"{(potencia_media_kw/total_demanda_pico_kw)*100:.1f}%")
        p3.metric("Uso vs Instalada", f"{(potencia_media_kw/total_instalado_kw)*100:.1f}%")

        if potencia_media_kw < 0.7 * total_demanda_pico_kw:
            st.success("O uso real está **bem abaixo** do pico — dimensionamento folgado.")
        elif potencia_media_kw < total_demanda_pico_kw:
            st.info("O uso está **dentro da capacidade**, mas mais próximo do limite.")
        else:
            st.warning("⚠️ O uso real **ultrapassa o pico estimado** — revise a demanda.")

    # ---------------------------------------------------
    # TAB 2 — CONSUMO (kWh)
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
    # TAB 3 — VIABILIDADE / ROI
    # ---------------------------------------------------
    with tab3:
        st.subheader("💡 Estudo de Viabilidade (ROI)")

        col_input, col_result = st.columns([1, 2])
        with col_input:
            investimento = st.number_input("Verba disponível", 50000.0, step=5000.0)
            st.caption("Considerando upgrades: LED e Ar Inverter.")

        eco_kwh = (consumo_total_kwh * 0.4 * 0.4) + (consumo_total_kwh * 0.3 * 0.6)
        eco_rs = eco_kwh * tarifa_kwh
        payback = investimento / eco_rs if eco_rs > 0 else 999

        with col_result:
            st.metric("Economia Mensal", f"R$ {eco_rs:,.2f}")
            st.metric("Payback", f"{payback:.1f} meses")

            if payback < 12:
                st.success("Alta viabilidade.")
            elif payback < 36:
                st.info("Viabilidade média.")
            else:
                st.warning("Retorno muito longo.")

    # ---------------------------------------------------
    # TAB 4 — DETALHES POR ANDAR / SALA
    # ---------------------------------------------------
    with tab4:
        st.subheader("🏢 Detalhes por Andar e Sala")

        col_a, col_s = st.columns(2)

        with col_a:
            st.markdown("### Andares")
            andares = sorted(df_raw['num_andar'].unique())
            a = st.selectbox("Selecione o Andar:", andares)
            df_a = df_raw[df_raw['num_andar'] == a]
            st.metric(f"Custo Total — {a}", f"R$ {df_a['Custo_Consumo_R$'].sum():,.2f}")

            st.dataframe(
                df_a.groupby('Id_sala')['Custo_Consumo_R$'].sum().reset_index().sort_values('Custo_Consumo_R$', ascending=False),
                use_container_width=True, hide_index=True
            )

        with col_s:
            st.markdown("### Salas")
            salas = sorted(df_raw['Id_sala'].unique())
            s = st.selectbox("Selecione a Sala:", salas)
            df_s = df_raw[df_raw['Id_sala'] == s]
            st.metric(f"Custo Total — {s}", f"R$ {df_s['Custo_Consumo_R$'].sum():,.2f}")
            st.dataframe(
                df_s[['des_nome_equipamento','Quant','Potencia_Instalada_kW','Custo_Consumo_R$']]
                .sort_values('Custo_Consumo_R$', ascending=False),
                use_container_width=True, hide_index=True
            )

else:
    st.warning("Carregando dados... Verifique a conexão com o GitHub se demorar.")
