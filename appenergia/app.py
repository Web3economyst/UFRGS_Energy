import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia", layout="wide", page_icon="⚡")

st.title("⚡ Gestão de Energia — Dimensionamento e Consumo")
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

        # Tratamento de Nulos para evitar erros de string depois
        df_inv['des_categoria'] = df_inv['des_categoria'].fillna('')
        df_inv['des_nome_equipamento'] = df_inv['des_nome_equipamento'].fillna('')

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
# 2. SIDEBAR
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros")
        
        st.subheader("🌦️ Sazonalidade")
        periodo = st.radio("Período:", ["Verão (Alto Consumo)", "Inverno (Baixo Consumo)"])
        
        tarifa_base = 0.65
        if "Verão" in periodo:
            fator_sazonal_clima = 1.30
            tarifa_sugerida = 0.72
        else:
            fator_sazonal_clima = 0.60
            tarifa_sugerida = 0.58

        st.subheader("💰 Tarifas")
        tarifa_kwh = st.number_input("R$/kWh", value=tarifa_sugerida, format="%.2f")
        tarifa_kw_demanda = st.number_input("R$/kW (Demanda)", value=40.0)

        st.divider()
        st.subheader("🕒 Salas 24h")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas:", lista_salas)

        with st.expander("Horas de Uso", expanded=True):
            horas_ar = st.slider("Climatização", 0, 24, 8)
            horas_pc = st.slider("Informática", 0, 24, 9)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_eletro = st.slider("Eletrodoméstico", 0, 24, 5)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias/Mês", value=22)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS (AGRUPAMENTO DUPLO: NOME + CATEGORIA)
    # ---------------------------------------------------

    def classificar_equipamento(row):
        # Cria um "texto de busca" juntando Categoria e Nome para não perder nada
        cat = str(row['des_categoria']).upper().strip()
        nome = str(row['des_nome_equipamento']).upper().strip()
        texto_busca = f"{cat} {nome}" 
        
        # 1. CLIMATIZAÇÃO
        if any(x in texto_busca for x in ['CLIM', 'AR COND', 'SPLIT', 'VENTILADOR', 'CONDICIONADO', 'TERMO']):
            return 'Climatização'
            
        # 2. ILUMINAÇÃO
        if any(x in texto_busca for x in ['ILUM', 'LAMP', 'LED', 'REFLETOR', 'LUMINARIA', 'PLAFON']):
            return 'Iluminação'
            
        # 3. INFORMÁTICA
        if any(x in texto_busca for x in ['INFORM', 'COMP', 'PC', 'MONIT', 'NOTE', 'TI', 'IMPRESSORA', 'RACK', 'WIFI', 'MODEM', 'SWITCH', 'NOBREAK', 'PROJETOR']):
            return 'Informática'
            
        # 4. ELETRODOMÉSTICO (LISTA EXPANDIDA)
        termos_eletro = [
            "ELETRO", "GELADEIRA", "MICRO", "CAFÉ", "CAFE", "FRIGOBAR", 
            "BEBEDOURO", "REFRIGERADOR", "FREEZER", "FOGÃO", "FOGAO", 
            "FORNO", "JARRA", "CHALEIRA", "LAVADORA", "SECADORA", "TORRADEIRA"
        ]
        if any(x in texto_busca for x in termos_eletro):
            return 'Eletrodoméstico'
            
        # 5. OUTROS
        if "ELEV" in texto_busca: return "Outros" # Elevadores podem ser tratados à parte ou em Outros
        if "BOMB" in texto_busca: return "Outros"
        
        return 'Outros'

    # APLICA A CLASSIFICAÇÃO NA LINHA INTEIRA (IMPORTANTE)
    df_raw['Categoria_Macro'] = df_raw.apply(classificar_equipamento, axis=1)

    # Consumo
    def calc_consumo(row):
        cat = row['Categoria_Macro']
        if str(row['Id_sala']) in salas_24h:
            h = 24
            dias = 30
        else:
            if cat == "Climatização": h = horas_ar
            elif cat == "Informática": h = horas_pc
            elif cat == "Iluminação": h = horas_luz
            elif cat == "Eletrodoméstico": h = horas_eletro
            else: h = horas_outros
            dias = dias_mes

        cons = (row['Potencia_Total_Item_W'] * h * dias) / 1000
        if cat == 'Climatização': return cons * fator_sazonal_clima
        return cons

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Consumo_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh

    # Demanda
    fatores_demanda = {
        'Climatização': 0.85,
        'Informática': 0.70,
        'Iluminação': 1.00,
        'Eletrodoméstico': 0.50,
        'Outros': 0.50
    }
    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5), axis=1
    )

    # Totais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()

    # ---------------------------------------------------
    # 4. TABS
    # ---------------------------------------------------
    tab1, tab2, tab_eff, tab3, tab4 = st.tabs([
        "📉 Dimensionamento",
        "⚡ Consumo",
        "💡 Eficiência",
        "💰 Viabilidade",
        "🏫 Detalhes"
    ])

    # --- TAB 1: DIMENSIONAMENTO ---
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", f"{total_instalado_kw:,.1f} kW")
        k2.metric("Pico Estimado", f"{total_demanda_pico_kw:,.1f} kW")
        k3.metric("Custo Fixo (Demanda)", f"R$ {custo_demanda_fixo:,.2f}")
        
        pico = 0
        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            if pd.isna(pico): pico = 0
        k4.metric("Pico Pessoas", f"{int(pico)}")

        st.divider()
        if not df_ocupacao.empty:
            fig_oc = px.line(df_ocupacao, x="DataHora", y="Ocupacao_Acumulada", title="Fluxo de Pessoas")
            st.plotly_chart(fig_oc, use_container_width=True)

        c_gauge, c_info = st.columns([1, 1.5])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number", value=total_demanda_pico_kw,
                title={'text': "Uso Infraestrutura (kW)"},
                gauge={'axis': {'range': [None, total_instalado_kw]}, 'bar': {'color': "#1f77b4"}}
            ))
            st.plotly_chart(fig_gauge, use_container_width=True)
            st.info(f"Trafo recomendado: {total_demanda_pico_kw/0.92:.0f} kVA")

        with c_info:
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Custo R$'] = dft['Demanda_Estimada_kW'] * tarifa_kw_demanda
            st.dataframe(dft.sort_values('Demanda_Estimada_kW', ascending=False), use_container_width=True, hide_index=True)

        # Comparativo Real vs Estimado
        pot_media = consumo_total_kwh / 720
        st.markdown("### 🔎 Uso Real vs Estimado")
        c_cmp1, c_cmp2, c_cmp3 = st.columns(3)
        c_cmp1.metric("Potência Média Real", f"{pot_media:.1f} kW")
        c_cmp2.metric("Uso vs Pico", f"{(pot_media/total_demanda_pico_kw)*100:.1f}%" if total_demanda_pico_kw>0 else "0%")
        c_cmp3.metric("Status", "✅ OK" if pot_media < total_demanda_pico_kw else "🚨 Crítico")

    # --- TAB 2: CONSUMO ---
    with tab2:
        st.subheader("⚡ Consumo Mensal")
        k1, k2, k3 = st.columns(3)
        k1.metric("Total kWh", f"{consumo_total_kwh:,.0f}")
        k2.metric("Custo Variável", f"R$ {custo_total_consumo:,.2f}")
        k3.metric("Fatura Estimada", f"R$ {(custo_demanda_fixo + custo_total_consumo):,.2f}")

        st.divider()
        fig_bar = px.bar(df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index(), 
                         x='Categoria_Macro', y='Consumo_Mensal_kWh', title="Consumo por Categoria", text_auto='.2s')
        st.plotly_chart(fig_bar, use_container_width=True)

    # --- TAB 3: EFICIÊNCIA ---
    with tab_eff:
        st.subheader("💡 Eficiência Energética")
        
        # Parâmetros de Redução
        eficiencia_params = {
            "Iluminação": 0.60,
            "Climatização": 0.35,
            "Informática": 0.40,
            "Eletrodoméstico": 0.20,
            "Outros": 0.05
        }

        resumo = df_raw.groupby("Categoria_Macro")["Consumo_Mensal_kWh"].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params).fillna(0)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        resumo["Economia_R$"] = resumo["Economia_kWh"] * tarifa_kwh

        c1, c2 = st.columns(2)
        c1.metric("Economia Potencial (kWh)", f"{resumo['Economia_kWh'].sum():,.0f}")
        c2.metric("Economia Potencial (R$)", f"R$ {resumo['Economia_R$'].sum():,.2f}")

        st.dataframe(resumo.style.format({"Reducao_%": "{:.0%}", "Economia_R$": "R$ {:,.2f}"}), use_container_width=True)

        fig_eco = px.bar(resumo, x="Categoria_Macro", y="Economia_R$", title="Economia por Categoria (R$)", text_auto='.2s')
        st.plotly_chart(fig_eco, use_container_width=True)

    # --- TAB 4: VIABILIDADE ---
    with tab3:
        st.subheader("💰 ROI do Projeto")
        cl, cr = st.columns([1, 2])
        with cl:
            inv = st.number_input("Investimento (R$)", 50000.0)
            custo_led = st.number_input("Custo LED (un)", 25.0)
            custo_ar = st.number_input("Custo Ar (un)", 3500.0)
        
        with cr:
            # Contagem real do inventário
            q_luz = df_raw[df_raw["Categoria_Macro"]=="Iluminação"]["Quant"].sum()
            q_ar = df_raw[df_raw["Categoria_Macro"]=="Climatização"]["Quant"].sum()
            
            # Cálculo simples de substituição
            troca_luz = min(int(inv / custo_led), int(q_luz))
            resto = inv - (troca_luz * custo_led)
            troca_ar = min(int(resto / custo_ar), int(q_ar))
            
            col1, col2 = st.columns(2)
            col1.metric("LEDs Trocados", f"{troca_luz}")
            col2.metric("Ar Trocados", f"{troca_ar}")
            
            # Economia
            eco_luz = troca_luz * (0.030 * horas_luz * dias_mes * tarifa_kwh * 0.6)
            eco_ar = troca_ar * (1.4 * horas_ar * dias_mes * tarifa_kwh * 0.35)
            eco_tot = eco_luz + eco_ar
            payback = inv / eco_tot if eco_tot > 0 else 999
            
            st.metric("Economia Mensal Gerada", f"R$ {eco_tot:,.2f}")
            st.metric("Payback", f"{payback:.1f} meses")

    # --- TAB 5: DETALHES ---
    with tab4:
        st.subheader("🏫 Detalhes")
        c1, c2 = st.columns(2)
        with c1:
            andar = st.selectbox("Andar", sorted(df_raw['num_andar'].unique()))
            st.dataframe(df_raw[df_raw['num_andar']==andar][['des_nome_equipamento', 'Quant', 'Custo_Consumo_R$']], use_container_width=True)
        with c2:
            sala = st.selectbox("Sala", sorted(df_raw['Id_sala'].unique()))
            st.dataframe(df_raw[df_raw['Id_sala']==sala][['des_nome_equipamento', 'Quant', 'Custo_Consumo_R$']], use_container_width=True)

else:
    st.warning("Aguardando dados...")
