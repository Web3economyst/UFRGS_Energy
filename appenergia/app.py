import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia (Engenharia)", layout="wide", page_icon="⚡")

st.title("⚡ Gestão de Energia: Demanda e Contratos")
st.markdown("""
Monitoramento técnico focado em **Contratos de Energia (Grupo A)**, dimensionamento de demanda e fator de potência.
""")

# --- 1. CARREGAMENTO E TRATAMENTO DE DADOS ---
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # --- A. CARGA INVENTÁRIO (CSV) ---
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='cp1252', on_bad_lines='skip') 
        df_inv.columns = df_inv.columns.str.strip()
        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)

        # Tratamento de Strings
        if 'num_andar' in df_inv.columns:
            df_inv['num_andar'] = df_inv['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df_inv['num_andar'] = 'Não Identificado'
            
        if 'Id_sala' in df_inv.columns:
            df_inv['Id_sala'] = df_inv['Id_sala'].astype(str).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df_inv['Id_sala'] = 'Não Identificado'
        
        # Conversão de Potência (BTU -> Watts)
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row['des_potencia']).upper().strip() if pd.notna(row['des_potencia']) else ""
            return p * 0.293 / 3.0 if 'BTU' in u else p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']
        
        # --- B. CARGA OCUPAÇÃO (EXCEL) ---
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba_dados = None
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                cols_limpas = [str(c).strip() for c in df_temp.columns]
                if 'DataHora' in cols_limpas and 'EntradaSaida' in cols_limpas:
                    nome_aba_dados = aba
                    break
            if not nome_aba_dados: nome_aba_dados = xls.sheet_names[0]

            df_oc = pd.read_excel(xls, sheet_name=nome_aba_dados)
            df_oc = df_oc.loc[:, ~df_oc.columns.duplicated()]
            df_oc.columns = df_oc.columns.astype(str).str.strip()
            
            if 'DataHora' in df_oc.columns and 'EntradaSaida' in df_oc.columns:
                df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
                df_oc = df_oc.dropna(subset=['DataHora']).sort_values('DataHora').reset_index(drop=True)
                df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str.strip().str[0].map({'E': 1, 'S': -1}).fillna(0)
                df_oc['Data_Dia'] = df_oc['DataHora'].dt.date
                
                def calcular_saldo_diario(grupo):
                    grupo = grupo.sort_values('DataHora')
                    grupo['Ocupacao_Dia'] = grupo['Variacao'].cumsum()
                    min_val = grupo['Ocupacao_Dia'].min()
                    if min_val < 0: grupo['Ocupacao_Dia'] += abs(min_val)
                    return grupo

                df_oc = df_oc.groupby('Data_Dia', group_keys=False).apply(calcular_saldo_diario)
                df_oc['Ocupacao_Acumulada'] = df_oc['Ocupacao_Dia']
            else:
                df_oc = pd.DataFrame()
        except Exception:
            df_oc = pd.DataFrame()

        return df_inv, df_oc

    except Exception as e:
        st.error(f"Erro crítico ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

if not df_raw.empty:
    # --- 2. SIDEBAR: CONTRATOS E PERFIL ---
    with st.sidebar:
        st.header("⚙️ Parâmetros do Contrato")
        
        st.subheader("📋 Contrato com a Concessionária")
        demanda_contratada = st.number_input("Demanda Contratada (kW)", value=300.0, step=10.0, help="Valor fixo pago mensalmente pela disponibilidade.")
        fp_alvo = st.number_input("Fator de Potência Mínimo", value=0.92, step=0.01, help="Abaixo disso paga-se multa de reativo.")
        
        st.divider()
        st.subheader("💰 Tarifas")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=0.65)
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.00)
        
        st.divider()
        st.subheader("🕒 Operação")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas 24h (Servidores/Críticas):", lista_salas)
        
        with st.expander("Horas de Uso (Geral)", expanded=False):
            horas_ar = st.slider("Ar Condicionado", 0, 24, 8)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_pc = st.slider("TI/Computadores", 0, 24, 9)
            horas_eletro = st.slider("Eletrodomésticos", 0, 24, 5)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias úteis/mês", value=22)

    # --- 3. CÁLCULOS TÉCNICOS ---
    def agrupar_categoria(cat):
        c = str(cat).upper()
        if 'CLIMATIZAÇÃO' in c or 'AR CONDICIONADO' in c: return 'Climatização'
        if 'ILUMINAÇÃO' in c or 'LÂMPADA' in c: return 'Iluminação'
        if 'INFORMÁTICA' in c or 'COMPUTADOR' in c or 'MONITOR' in c: return 'Informática'
        if 'ELETRODOMÉSTICO' in c: return 'Eletrodomésticos'
        if 'ELEVADOR' in c: return 'Elevadores'
        if 'BOMBA' in c: return 'Bombas'
        return 'Outros'

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar_categoria)
    
    # 3.1 CÁLCULO DE CONSUMO (Energia - kWh)
    def calc_consumo(row):
        if str(row['Id_sala']) in salas_24h:
            h = 24
            dias_calculo = 30
        else:
            cat = row['Categoria_Macro']
            if cat == 'Climatização': h = horas_ar
            elif cat == 'Iluminação': h = horas_luz
            elif cat == 'Informática': h = horas_pc
            elif cat == 'Eletrodomésticos': h = horas_eletro
            else: h = horas_outros
            dias_calculo = dias_mes
        return (row['Potencia_Total_Item_W'] * h * dias_calculo) / 1000

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Consumo_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh
    
    # 3.2 CÁLCULO DE DEMANDA (Potência - kW)
    # Fatores de Demanda Típicos (Simultaneidade)
    fatores_demanda = {
        'Climatização': 0.85,    # Nem todos os compressores ligam juntos
        'Iluminação': 1.00,      # Geralmente tudo aceso no horário comercial
        'Informática': 0.70,     # Nem todos PCs em processamento máximo
        'Eletrodomésticos': 0.50,# Uso intermitente (cafeteira, microondas)
        'Elevadores': 0.30,      # Uso esporádico
        'Bombas': 0.70,
        'Outros': 0.50
    }
    
    # Potência Instalada (Soma simples das placas dos equipamentos)
    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    
    # Demanda Provável (Aplicando fator de simultaneidade)
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5), axis=1
    )

    # Agregações
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    
    # Ajuste Fino com Ocupação (Opcional: Se ocupação for muito baixa, reduz a demanda variável)
    if not df_ocupacao.empty and 'Ocupacao_Acumulada' in df_ocupacao.columns:
        pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
        if pd.isna(pico_pessoas): pico_pessoas = 100 # Valor default
    else:
        pico_pessoas = 0

    # 3.3 FATOR DE POTÊNCIA (kVA)
    # Estimativa simples: Assumindo FP atual médio de 0.88 (levemente indutivo) para simular correção
    fp_atual_simulado = 0.88 
    total_kva = total_demanda_pico_kw / fp_atual_simulado

    # --- 4. VISUALIZAÇÃO ---
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📉 Demanda & Contrato", 
        "⚡ Consumo (kWh)", 
        "💡 Eficiência & ROI", 
        "🏫 Detalhe Salas"
    ])

    # --- ABA 1: DEMANDA & CONTRATO (Foco do Usuário) ---
    with tab1:
        st.subheader("Monitoramento de Pico e Contrato de Energia")
        
        # Bloco Explicativo (Toggle)
        with st.expander("📚 Como é calculado o Pico de Demanda?", expanded=False):
            st.markdown(r"""
            **Diferença entre Consumo e Demanda:**
            
            1.  **Consumo (kWh):** É o acumulado do mês (Energia Total). Fórmula: $kWh = \sum (kW \times horas \times 30)$.
            2.  **Demanda de Pico (kW):** É a "largura do cano" necessária. É o momento de maior uso simultâneo.
            
            **O Cálculo da Demanda neste Painel:**
            Somamos a potência de todos os equipamentos e aplicamos um **Fator de Demanda (FD)**, pois nem tudo liga ao mesmo tempo.
            
            * $P_{Ar} \times 0.85$ (Compressores ciclam)
            * $P_{Luz} \times 1.00$ (Tudo aceso)
            * $P_{Tomadas} \times 0.50$ (Uso aleatório)
            
            **Por que importa?** Se o Pico Estimado > Demanda Contratada, você paga multa de ultrapassagem (normalmente 2x a tarifa).
            """)

        # KPIs Principais
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Potência Instalada Total", f"{total_instalado_kw:,.1f} kW", help="Soma das placas de todos equipamentos")
        
        delta_demanda = demanda_contratada - total_demanda_pico_kw
        cor_delta = "normal" if delta_demanda >= 0 else "inverse"
        label_delta = "Dentro do Contrato" if delta_demanda >= 0 else "⚠️ Ultrapassagem (Multa)"
        
        col2.metric("Pico de Demanda Estimado", f"{total_demanda_pico_kw:,.1f} kW", delta=f"{label_delta}", delta_color=cor_delta)
        col3.metric("Demanda Contratada", f"{demanda_contratada:,.1f} kW", help="Custo Fixo Mensal")
        
        # Custo da Demanda
        custo_fixo_demanda = demanda_contratada * tarifa_kw_demanda
        multa_est = 0
        if total_demanda_pico_kw > demanda_contratada:
            multa_est = (total_demanda_pico_kw - demanda_contratada) * tarifa_kw_demanda * 2 # Multa aprox 2x
        
        col4.metric("Fatura de Demanda", f"R$ {custo_fixo_demanda:,.2f}", delta=f"+ R$ {multa_est:,.2f} Multa" if multa_est > 0 else "Sem Multa", delta_color="inverse")

        st.divider()

        # Gráfico Gauge (Velocímetro) - Visualização Clara da Ultrapassagem
        c_gauge, c_tbl = st.columns([1, 1.5])
        
        with c_gauge:
            max_gauge = max(demanda_contratada * 1.5, total_instalado_kw)
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = total_demanda_pico_kw,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Utilização da Demanda (kW)"},
                delta = {'reference': demanda_contratada, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
                gauge = {
                    'axis': {'range': [None, max_gauge]},
                    'bar': {'color': "black", 'opacity':0.7},
                    'steps': [
                        {'range': [0, demanda_contratada * 0.9], 'color': "#90EE90"}, # Verde
                        {'range': [demanda_contratada * 0.9, demanda_contratada], 'color': "#FFFFE0"}, # Amarelo
                        {'range': [demanda_contratada, max_gauge], 'color': "#FFB6C1"}], # Vermelho
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': demanda_contratada}
                }
            ))
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            # Análise de Fator de Potência (Extra)
            st.markdown("#### 🧮 Fator de Potência (kVA)")
            kVA_calc = total_demanda_pico_kw / fp_atual_simulado
            st.info(f"""
            Estimativa considerando FP atual de **{fp_atual_simulado}**:
            * Potência Aparente Necessária: **{kVA_calc:,.1f} kVA**
            * Transformador Recomendado: **{500 if kVA_calc < 450 else 750} kVA**
            * Meta de FP: **{fp_alvo}** (Se < {fp_alvo} gera multa de reativo).
            """)

        with c_tbl:
            st.markdown("#### Composição da Demanda por Carga")
            df_demanda_cat = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            # Adiciona coluna do Fator usado
            df_demanda_cat['Fator Demanda'] = df_demanda_cat['Categoria_Macro'].map(fatores_demanda)
            df_demanda_cat = df_demanda_cat.sort_values('Demanda_Estimada_kW', ascending=False)
            
            st.dataframe(
                df_demanda_cat.style.format({
                    "Potencia_Instalada_kW": "{:.1f} kW",
                    "Demanda_Estimada_kW": "{:.1f} kW",
                    "Fator Demanda": "{:.2f}"
                }), 
                use_container_width=True,
                hide_index=True
            )

    # --- ABA 2: CONSUMO (kWh) ---
    with tab2:
        st.subheader("Consumo de Energia (Fatura Variável)")
        
        custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
        consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
        
        k1, k2 = st.columns(2)
        k1.metric("Consumo Mensal Total", f"{consumo_total_kwh:,.0f} kWh")
        k2.metric("Custo do Consumo", f"R$ {custo_total_consumo:,.2f}", help="Não inclui o custo da demanda fixa")
        
        st.divider()
        c_bar, c_pie = st.columns([2, 1])
        with c_bar:
            fig_bar = px.bar(
                df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index(),
                x='Categoria_Macro', y='Consumo_Mensal_kWh', color='Categoria_Macro', 
                title="Consumo por Categoria (kWh)", text_auto='.2s'
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with c_pie:
            st.markdown("**Representatividade no Custo**")
            fig_pie = px.pie(df_raw, values='Custo_Consumo_R$', names='Categoria_Macro', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- ABA 3: EFICIÊNCIA & ROI ---
    with tab3:
        st.subheader("Estudo de Viabilidade (Retrofit)")
        
        # Simulador simples
        col_input, col_result = st.columns([1, 2])
        
        with col_input:
            st.markdown("##### Parâmetros do Projeto")
            investimento = st.number_input("Verba Disponível (R$)", 50000.0, step=5000.0)
            st.caption("Focando em troca de iluminação (LED) e Ar Condicionado (Inverter).")
        
        with col_result:
            # Cálculo simplificado de economia
            # Assumindo que 40% do consumo é Ar e 30% é Luz
            eco_potencial_kwh = (consumo_total_kwh * 0.4 * 0.4) + (consumo_total_kwh * 0.3 * 0.6) # 40% eco no ar, 60% na luz
            eco_financeira = eco_potencial_kwh * tarifa_kwh
            payback = investimento / eco_financeira if eco_financeira > 0 else 0
            
            st.markdown("##### Resultados Projetados")
            m1, m2, m3 = st.columns(3)
            m1.metric("Economia Mensal Estimada", f"R$ {eco_financeira:,.2f}")
            m2.metric("Redução de Carga (Alívio Demanda)", f"{total_demanda_pico_kw * 0.15:,.1f} kW", help="Estima-se 15% de queda na demanda de pico.")
            m3.metric("Payback Simples", f"{payback:.1f} meses")
            
            if payback < 12:
                st.success("✅ Projeto de altíssima viabilidade (Payback < 1 ano)")
            elif payback < 36:
                st.info("⚠️ Viabilidade média (1 a 3 anos)")
            else:
                st.warning("❌ Payback longo. Reavaliar escopo.")

    # --- ABA 4: DETALHE SALAS ---
    with tab4:
        st.subheader("Consulta por Ambiente")
        sel_sala = st.selectbox("Selecione a Sala:", sorted(df_raw['Id_sala'].unique().astype(str)))
        
        if sel_sala:
            df_s = df_raw[df_raw['Id_sala'] == sel_sala]
            st.dataframe(df_s[['des_nome_equipamento', 'Quant', 'Potencia_Instalada_kW', 'Demanda_Estimada_kW', 'Consumo_Mensal_kWh']])

else:
    st.info("Aguardando dados... Se o erro persistir, verifique a conexão com o GitHub.")
