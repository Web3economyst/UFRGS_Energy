import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia (Dimensionamento)", layout="wide", page_icon="⚡")

st.title("⚡ Gestão de Energia: Dimensionamento de Demanda")
st.markdown("""
Painel de gestão de contratos de energia, dimensionamento de demanda e análise de viabilidade de projetos de eficiência.
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

        if 'num_andar' in df_inv.columns:
            df_inv['num_andar'] = df_inv['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df_inv['num_andar'] = 'Não Identificado'
            
        if 'Id_sala' in df_inv.columns:
            df_inv['Id_sala'] = df_inv['Id_sala'].astype(str).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df_inv['Id_sala'] = 'Não Identificado'
        
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
    # --- 2. SIDEBAR COM SAZONALIDADE ---
    with st.sidebar:
        st.header("⚙️ Parâmetros & Sazonalidade")
        
        # Sazonalidade
        st.subheader("🌦️ Período de Análise")
        periodo = st.radio("Selecione a Estação:", ["Verão (Alto Consumo Ar)", "Inverno/Ameno (Baixo Consumo Ar)"])
        
        # Lógica de Tarifas baseada na estação (Exemplo: Verão tarifa mais cara ou igual)
        tarifa_padrao = 0.65
        if "Verão" in periodo:
            fator_sazonal_clima = 1.30 # Ar condicionado consome 30% a mais
            tarifa_sugerida = 0.72     # Tarifa um pouco mais cara (Bandeira)
        else:
            fator_sazonal_clima = 0.60 # Ar condicionado consome 40% a menos
            tarifa_sugerida = 0.58     # Tarifa base
        
        st.divider()
        st.subheader("💰 Tarifas (Ajustáveis)")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=tarifa_sugerida, format="%.2f", help="Ajustado conforme estação selecionada acima.")
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.00, help="Preço fixo da potência.")
        
        st.divider()
        st.subheader("🕒 Salas Críticas (24h)")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Selecione Salas 24h:", lista_salas)
        
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
    
    # Consumo kWh com SAZONALIDADE
    def calc_consumo(row):
        cat = row['Categoria_Macro']
        
        # Lógica de Horas
        if str(row['Id_sala']) in salas_24h:
            h = 24
            dias_calculo = 30
        else:
            if cat == 'Climatização': h = horas_ar
            elif cat == 'Iluminação': h = horas_luz
            elif cat == 'Informática': h = horas_pc
            elif cat == 'Eletrodomésticos': h = horas_eletro
            else: h = horas_outros
            dias_calculo = dias_mes
            
        consumo_base = (row['Potencia_Total_Item_W'] * h * dias_calculo) / 1000
        
        # Aplica Sazonalidade apenas no Ar Condicionado
        if cat == 'Climatização':
            return consumo_base * fator_sazonal_clima
        return consumo_base

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Consumo_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh
    
    # Demanda kW
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
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5), axis=1
    )

    # --- TOTAIS GLOBAIS ---
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    
    # Custos
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
    
    # --- 4. VISUALIZAÇÃO ---
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📉 Dimensionamento Demanda", 
        "⚡ Consumo (kWh)", 
        "💡 Viabilidade & Eficiência", 
        "🏫 Detalhe Salas"
    ])

    # --- ABA 1: DIMENSIONAMENTO ---
    with tab1:
        st.subheader("Análise de Demanda (Custo Fixo de Disponibilidade)")
        st.caption(f"Cenário Considerado: **{periodo}** (Fator Clima: {fator_sazonal_clima}x)")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Potência Instalada", f"{total_instalado_kw:,.1f} kW")
        col2.metric("Pico Estimado", f"{total_demanda_pico_kw:,.1f} kW")
        col3.metric("Custo Fixo (Demanda)", f"R$ {custo_demanda_fixo:,.2f}")
        
        if not df_ocupacao.empty:
            pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
            if pd.isna(pico_pessoas): pico_pessoas = 0
            col4.metric("Pico de Ocupação", f"{int(pico_pessoas)} Pessoas")
        else:
            col4.metric("Pico de Ocupação", "N/A")

        st.divider()

        # Gauge & Comparação Automática
        c_gauge, c_comp = st.columns([1, 1.5])
        
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = total_demanda_pico_kw,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Infraestrutura (kW)"},
                gauge = {
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "rgba(31, 119, 180, 0.8)"}, 
                    'steps': [
                        {'range': [0, total_demanda_pico_kw], 'color': "rgba(0,0,0,0)"},
                        {'range': [total_demanda_pico_kw, total_instalado_kw], 'color': "#f0f2f6"}],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': total_demanda_pico_kw}
                }
            ))
            st.plotly_chart(fig_gauge, use_container_width=True)

        with c_comp:
            st.markdown("### 🔎 Comparação: Uso Real vs Capacidade")
            potencia_media_kw = consumo_total_kwh / 720 
            pct_uso_demanda = (potencia_media_kw / total_demanda_pico_kw) * 100 if total_demanda_pico_kw > 0 else 0
            pct_uso_instalada = (potencia_media_kw / total_instalado_kw) * 100 if total_instalado_kw > 0 else 0

            k_cmp1, k_cmp2 = st.columns(2)
            k_cmp1.metric("Potência Média (Uso Real)", f"{potencia_media_kw:,.1f} kW")
            k_cmp2.metric("Uso vs Pico Estimado", f"{pct_uso_demanda:.1f}%")

            if pct_uso_demanda < 70:
                st.success("✅ O uso real está confortável dentro do dimensionamento.")
            elif pct_uso_demanda < 100:
                st.info("⚠️ O uso real está próximo do pico estimado.")
            else:
                st.warning("🚨 O uso REAL ultrapassa o pico estimado.")
            
            # Tabela Resumida
            df_demanda_cat = df_raw.groupby('Categoria_Macro')[['Demanda_Estimada_kW']].sum().reset_index()
            df_demanda_cat['Custo Demanda (R$)'] = df_demanda_cat['Demanda_Estimada_kW'] * tarifa_kw_demanda
            st.dataframe(df_demanda_cat.sort_values('Demanda_Estimada_kW', ascending=False), use_container_width=True, hide_index=True)

    # --- ABA 2: CONSUMO ---
    with tab2:
        st.subheader("Consumo de Energia (Custo Variável)")
        fatura_total_estimada = custo_demanda_fixo + custo_total_consumo
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Consumo Mensal", f"{consumo_total_kwh:,.0f} kWh")
        k2.metric("Custo Variável", f"R$ {custo_total_consumo:,.2f}")
        k3.metric("Fatura Total Estimada", f"R$ {fatura_total_estimada:,.2f}", delta="Fixo + Variável", delta_color="off")
        
        st.divider()
        fig_bar = px.bar(
            df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index(),
            x='Categoria_Macro', y='Consumo_Mensal_kWh', color='Categoria_Macro', 
            title="Consumo por Categoria (kWh)", text_auto='.2s'
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # --- ABA 3: VIABILIDADE (ATUALIZADA) ---
    with tab3:
        st.subheader("Estudo de Viabilidade e Redução de Custos")
        
        col_input, col_graf = st.columns([1, 2])
        
        with col_input:
            st.markdown("#### ⚙️ Parâmetros do Projeto")
            investimento = st.number_input("Verba para Investimento (R$)", 50000.0, step=5000.0)
            st.info("""
            **Propostas Automáticas:**
            1. Substituição de Iluminação por **LED** (-60% consumo luz).
            2. Ar Condicionado **Inverter** (-40% consumo clima).
            3. Ajuste de Contrato de Demanda (Evitar multas).
            """)
        
        # Cálculos de Economia
        eco_potencial_kwh = (consumo_total_kwh * 0.4 * 0.4) + (consumo_total_kwh * 0.3 * 0.6) # Estimativa
        eco_financeira = eco_potencial_kwh * tarifa_kwh
        novo_custo_consumo = custo_total_consumo - eco_financeira
        
        # Comparativo Gráfico
        with col_graf:
            st.markdown("#### 📊 Comparativo: Atual vs Econômico")
            
            # Dados para o gráfico
            dados_comp = pd.DataFrame({
                'Cenário': ['Cenário Atual', 'Cenário Eficiente'],
                'Custo Mensal (R$)': [custo_total_consumo, novo_custo_consumo],
                'Cor': ['#EF553B', '#00CC96'] # Vermelho, Verde
            })
            
            fig_comp = px.bar(
                dados_comp, x='Cenário', y='Custo Mensal (R$)', 
                color='Cenário', color_discrete_sequence=['#EF553B', '#00CC96'],
                text='Custo Mensal (R$)'
            )
            fig_comp.update_traces(texttemplate='R$ %{text:,.2f}', textposition='outside')
            fig_comp.update_layout(showlegend=False, height=300)
            st.plotly_chart(fig_comp, use_container_width=True)

        st.divider()
        
        # Resultados Financeiros
        payback = investimento / eco_financeira if eco_financeira > 0 else 0
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Economia Mensal Gerada", f"R$ {eco_financeira:,.2f}", delta="Dinheiro economizado")
        m2.metric("Redução na Conta (%)", f"{(eco_financeira/custo_total_consumo)*100:.1f}%")
        
        if payback < 18:
            cor_delta = "normal" # Verde
            txt_payback = "✅ Retorno Rápido"
        elif payback < 36:
            cor_delta = "off" # Cinza
            txt_payback = "⚠️ Retorno Médio"
        else:
            cor_delta = "inverse" # Vermelho
            txt_payback = "❌ Retorno Longo"
            
        m3.metric("Payback (Retorno)", f"{payback:.1f} meses", delta=txt_payback, delta_color=cor_delta)

    # --- ABA 4: DETALHE SALAS ---
    with tab4:
        st.subheader("Detalhamento por Nível e Ambiente")
        col_andar, col_sala = st.columns(2)
        
        with col_andar:
            st.markdown("### 🏢 Por Andar")
            andares = sorted(df_raw['num_andar'].unique().astype(str))
            sel_andar = st.selectbox("Selecione o Andar:", andares)
            if sel_andar:
                df_a = df_raw[df_raw['num_andar'] == sel_andar]
                custo_andar = df_a['Custo_Consumo_R$'].sum()
                st.metric(f"Custo Total - {sel_andar}", f"R$ {custo_andar:,.2f}")
                st.caption("Maiores consumidores:")
                df_a_agrupado = df_a.groupby('Id_sala')[['Custo_Consumo_R$']].sum().reset_index().sort_values('Custo_Consumo_R$', ascending=False)
                st.dataframe(df_a_agrupado.style.format({"Custo_Consumo_R$": "R$ {:.2f}"}), use_container_width=True, hide_index=True)

        with col_sala:
            st.markdown("### 🚪 Por Sala")
            salas = sorted(df_raw['Id_sala'].unique().astype(str))
            sel_sala = st.selectbox("Selecione a Sala:", salas)
            if sel_sala:
                df_s = df_raw[df_raw['Id_sala'] == sel_sala]
                custo_sala = df_s['Custo_Consumo_R$'].sum()
                st.metric(f"Custo Total - {sel_sala}", f"R$ {custo_sala:,.2f}")
                st.caption("Lista de equipamentos:")
                st.dataframe(
                    df_s[['des_nome_equipamento', 'Quant', 'Potencia_Instalada_kW', 'Custo_Consumo_R$']].sort_values('Custo_Consumo_R$', ascending=False),
                    use_container_width=True, hide_index=True
                )

else:
    st.info("Aguardando dados... Se o erro persistir, verifique a conexão com o GitHub.")
