import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ---------------------------------------------------
st.set_page_config(
    page_title="Dashboard Energético - Reitoria",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------
# ESTILOS CSS PERSONALIZADOS
# ---------------------------------------------------
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    .big-font {
        font-size: 18px !important;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Sistema de Inteligência Energética — Reitoria")
st.markdown("""
**Diagnóstico "As-Is" & Simulação de Cenários** Modelagem baseada em inventário físico (Carga Instalada) cruzado com rotinas operacionais (Ponto Eletrônico) e estrutura tarifária **Grupo A4 (Verde)**.
""")

# ---------------------------------------------------
# FUNÇÕES UTILITÁRIAS
# ---------------------------------------------------
def formatar_br(valor, prefixo="", sufixo="", decimais=2):
    """Formata moeda e números para o padrão Brasileiro (Milhar com ponto, decimal com vírgula)"""
    try:
        if pd.isna(valor): return "-"
        formato = f"{{:,.{decimais}f}}"
        texto = formato.format(valor)
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{prefixo}{texto}{sufixo}"
    except:
        return str(valor)

# ---------------------------------------------------
# 1. CARREGAMENTO E TRATAMENTO DE DADOS (LÓGICA DO RELATÓRIO)
# ---------------------------------------------------
# URLs de fallback (caso local não exista)
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/refs/heads/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # --- CARGA INVENTÁRIO ---
        # Tenta ler CSV, lidando com encodings chatos
        try:
            df = pd.read_csv("Planilha Unificada.xlsx - Equipamentos Consumo.csv", encoding='utf-8')
        except:
            try:
                df = pd.read_csv(DATA_URL_INVENTARIO, encoding='utf-8', on_bad_lines='skip')
            except:
                 df = pd.read_csv(DATA_URL_INVENTARIO, encoding='latin1', on_bad_lines='skip')

        # Limpeza de Colunas
        df.columns = df.columns.str.strip()
        
        # Tratamento de Nulos e Tipos
        df['Quant'] = pd.to_numeric(df['Quant'], errors='coerce').fillna(1)
        df['num_potencia'] = pd.to_numeric(df['num_potencia'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        
        cols_txt = ['Setor', 'des_nome_generico_equipamento', 'des_categoria', 'des_potencia', 'Id_sala', 'num_andar']
        for c in cols_txt:
            if c in df.columns:
                df[c] = df[c].astype(str).str.strip().str.upper().replace(['NAN', 'NAN.0', ''], 'NÃO IDENTIFICADO')
            else:
                df[c] = 'NÃO IDENTIFICADO'

        # Ajuste no andar (remover .0)
        df['num_andar'] = df['num_andar'].str.replace(r'\.0$', '', regex=True)

        # --- LÓGICA DE IMPUTAÇÃO TÉCNICA (DO RELATÓRIO) ---
        def estimar_watts_reais(row):
            pot = row['num_potencia']
            unit = row['des_potencia']
            nome = row['des_nome_generico_equipamento']
            cat = row['des_categoria']

            # 1. Se potência zerada, imputar média de mercado
            if pot <= 0.1:
                if 'AR CONDICIONADO' in nome: return 1400.0 # ~12000 BTU antigo
                if 'COMPUTADOR' in nome: return 200.0
                if 'MONITOR' in nome: return 30.0
                if 'CHALEIRA' in nome: return 1200.0
                if 'CAFETEIRA' in nome: return 800.0
                if 'GELADEIRA' in nome: return 150.0 # Motor médio
                if 'LÂMPADA' in nome: return 32.0 # Tubular Fluorescente
                return 50.0 # Default genérico

            # 2. Conversão de Unidades
            if 'BTU' in unit: return (pot * 0.293) / 3.0 # Considera COP 3.0
            if 'CV' in unit or 'HP' in unit: return pot * 735.5
            if 'KW' in unit: return pot * 1000.0
            
            return float(pot)

        df['Potencia_Real_W'] = df.apply(estimar_watts_reais, axis=1)
        df['Potencia_Total_Instalada_W'] = df['Potencia_Real_W'] * df['Quant']

        # --- CARGA OCUPAÇÃO ---
        try:
            # Tenta ler Excel local ou remoto
            try:
                df_oc = pd.read_excel("Comportamento.xlsx") # Nome hipotético local
            except:
                xls = pd.ExcelFile(DATA_URL_OCUPACAO)
                df_oc = pd.read_excel(xls, sheet_name=0)
            
            if 'DataHora' in df_oc.columns:
                df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
                df_oc = df_oc.dropna(subset=['DataHora']).sort_values('DataHora')
                
                # Lógica de Fluxo Acumulado
                df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str[0].map({'E': 1, 'S': -1}).fillna(0)
                
                # Acumulado diário simples para gráfico
                df_oc['Data_Dia'] = df_oc['DataHora'].dt.date
                def get_day_flow(g):
                    g = g.sort_values('DataHora')
                    g['Ocupacao'] = g['Variacao'].cumsum()
                    # Normalizar para não começar negativo
                    m = g['Ocupacao'].min()
                    if m < 0: g['Ocupacao'] += abs(m)
                    return g
                
                df_oc = df_oc.groupby('Data_Dia', group_keys=False).apply(get_day_flow)
            else:
                df_oc = pd.DataFrame()
        except:
            df_oc = pd.DataFrame()

        return df, df_oc

    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

# ---------------------------------------------------
# 2. SIDEBAR - CONTROLES AVANÇADOS
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros Operacionais")
        
        # A. Sazonalidade
        st.subheader("1. Sazonalidade & Clima")
        periodo = st.radio("Cenário Climático:", ["Verão (Crítico)", "Inverno/Ameno"], index=0)
        
        # Impacto do verão: Ar condicionado trabalha mais (Duty Cycle maior) e Tarifa pode mudar
        if "Verão" in periodo:
            fator_clima_ar = 0.65 # Compressor liga 65% do tempo
            st.caption("🔥 Alta demanda de refrigeração.")
        else:
            fator_clima_ar = 0.30 # Compressor liga 30% do tempo
            st.caption("❄️ Baixa demanda de refrigeração.")

        # B. Tarifas
        st.divider()
        st.subheader("2. Estrutura Tarifária (A4)")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            tarifa_ponta = st.number_input("R$/kWh Ponta", value=2.90, format="%.2f", help="18h às 21h")
        with col_t2:
            tarifa_fora = st.number_input("R$/kWh F. Ponta", value=0.70, format="%.2f", help="Demais horários")
        
        tarifa_demanda = st.number_input("R$/kW Demanda", value=42.00, help="Custo fixo de disponibilidade")
        dias_uteis = st.slider("Dias Úteis / Mês", 18, 25, 22)

        # C. Salas Críticas
        st.divider()
        st.subheader("3. Exceções (24h)")
        salas_uniques = sorted(df_raw['Id_sala'].unique())
        salas_24h = st.multiselect("Salas com operação contínua:", salas_uniques)

        # D. Ajuste Fino
        with st.expander("🔧 Ajuste Fino de Uso (Duty Cycle)"):
            uso_pc = st.slider("Uso Efetivo Computadores (%)", 20, 100, 80) / 100.0
            uso_luz = st.slider("Uso Iluminação (Expediente)", 50, 100, 100) / 100.0

    # ---------------------------------------------------
    # 3. PROCESSAMENTO CENTRAL (MOTOR DE CÁLCULO)
    # ---------------------------------------------------
    
    # Categorização Macro
    def get_macro(cat):
        c = cat.upper()
        if 'CLIM' in c or 'AR' in c: return 'Climatização'
        if 'ILUM' in c or 'LÂMP' in c: return 'Iluminação'
        if 'INFORM' in c or 'COMP' in c or 'MONIT' in c: return 'Informática'
        if 'ELETRO' in c or 'COPA' in c: return 'Eletrodomésticos'
        return 'Outros'
    
    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(get_macro)

    # Cálculo Linha a Linha (Consumo e Custo)
    def calcular_linha(row):
        cat = row['Categoria_Macro']
        nome = row['des_nome_generico_equipamento']
        pot_kw = row['Potencia_Total_Instalada_W'] / 1000.0
        
        # Verifica se é equipamento 24h (Servidores, Geladeiras) ou Sala 24h
        is_always_on = (row['Id_sala'] in salas_24h) or \
                       any(x in nome for x in ['GELADEIRA', 'SERVIDOR', 'RACK', 'NOBREAK', 'FREEZER'])
        
        if is_always_on:
            horas_dia = 24
            dias = 30
            # Fator de uso (Geladeira cicla, Servidor não)
            fator = 0.45 if 'GELADEIRA' in nome else 1.0
            
            # Split Ponta (3h por dia útil aprox)
            horas_ponta_mes = 3 * dias_uteis
            horas_total_mes = 24 * 30
            horas_fora_mes = horas_total_mes - horas_ponta_mes
            
        else:
            # Horário Comercial (07:00 - 18:30)
            horas_dia = 11.5
            dias = dias_uteis
            
            # Fator de Uso
            if cat == 'Climatização': fator = fator_clima_ar
            elif cat == 'Informática': fator = uso_pc
            elif cat == 'Iluminação': fator = uso_luz
            elif any(x in nome for x in ['CHALEIRA', 'CAFETEIRA', 'MICROONDAS']):
                horas_dia = 1.0 # Uso pontual
                fator = 1.0
            else:
                fator = 0.5
            
            # Split Ponta (0.5h por dia útil -> 18:00 as 18:30)
            horas_ponta_mes = 0.5 * dias_uteis
            horas_total_mes = horas_dia * dias
            horas_fora_mes = max(0, horas_total_mes - horas_ponta_mes)

        # Energia
        kwh_mensal = pot_kw * horas_total_mes * fator
        
        # Custo (Proporcional às horas de ponta/fora calculadas)
        if horas_total_mes > 0:
            fracao_ponta = horas_ponta_mes / horas_total_mes
            kwh_p = kwh_mensal * fracao_ponta
            kwh_f = kwh_mensal * (1 - fracao_ponta)
            custo = (kwh_p * tarifa_ponta) + (kwh_f * tarifa_fora)
        else:
            custo = 0.0

        # Demanda Estimada (Simultaneidade no Pico)
        # Climatização pesa muito no pico, Iluminação tbm.
        fator_demanda = 0.5
        if cat == 'Climatização': fator_demanda = 0.85
        if cat == 'Iluminação': fator_demanda = 1.0
        if cat == 'Informática': fator_demanda = 0.7
        
        demanda_est = pot_kw * fator_demanda

        return pd.Series([kwh_mensal, custo, demanda_est])

    df_raw[['Consumo_kWh', 'Custo_R$', 'Demanda_kW']] = df_raw.apply(calcular_linha, axis=1)

    # Totais Globais
    total_inst_kw = df_raw['Potencia_Total_Instalada_W'].sum() / 1000
    total_cons_kwh = df_raw['Consumo_kWh'].sum()
    total_custo_consumo = df_raw['Custo_R$'].sum()
    total_demanda_pico = df_raw['Demanda_kW'].sum()
    total_custo_demanda = total_demanda_pico * tarifa_demanda
    
    fatura_estimada = total_custo_consumo + total_custo_demanda

    # ---------------------------------------------------
    # 4. DASHBOARD - VISUALIZAÇÃO (TABS)
    # ---------------------------------------------------
    
    # KPIs SUPERIORES
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fatura Mensal Estimada", formatar_br(fatura_estimada, "R$ "), 
              delta="Demanda + Consumo", delta_color="normal")
    c2.metric("Consumo Mensal", formatar_br(total_cons_kwh, sufixo=" kWh"),
              delta=f"{periodo}")
    c3.metric("Demanda de Pico", formatar_br(total_demanda_pico, sufixo=" kW"),
              delta=f"Instalada: {formatar_br(total_inst_kw)} kW", delta_color="off")
    
    ocupacao_max = int(df_ocupacao['Ocupacao'].max()) if not df_ocupacao.empty else 0
    c4.metric("Ocupação Máxima", f"{ocupacao_max} pessoas", "Ponto Eletrônico")

    st.markdown("---")

    tabs = st.tabs(["📉 Dimensionamento", "⚡ Consumo Detalhado", "💡 Eficiência", "💰 ROI & Investimento", "🔍 Detalhamento (Salas)"])

    # --- TAB 1: DIMENSIONAMENTO ---
    with tabs[0]:
        col_gauge, col_tbl = st.columns([1, 2])
        
        with col_gauge:
            st.markdown("### Utilização da Carga")
            # Gráfico de Velocímetro (Gauge)
            fig_g = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = total_demanda_pico,
                title = {'text': "Demanda Máx (kW)"},
                gauge = {
                    'axis': {'range': [None, total_inst_kw]},
                    'bar': {'color': "#2ecc71" if total_demanda_pico < total_inst_kw*0.8 else "#e74c3c"},
                    'steps': [
                        {'range': [0, total_inst_kw*0.5], 'color': "lightgray"},
                        {'range': [total_inst_kw*0.5, total_inst_kw], 'color': "gray"}],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': total_demanda_pico}
                }
            ))
            fig_g.update_layout(height=300, margin=dict(l=20,r=20,t=50,b=20))
            st.plotly_chart(fig_g, use_container_width=True)
            
            fator_carga = total_demanda_pico / total_inst_kw
            st.info(f"**Fator de Demanda Global:** {fator_carga:.2f}\n\nIndica que no pior cenário, {fator_carga*100:.0f}% dos equipamentos estão ligados simultaneamente.")

        with col_tbl:
            st.markdown("### Carga por Categoria")
            df_dim = df_raw.groupby('Categoria_Macro')[['Potencia_Total_Instalada_W', 'Demanda_kW']].sum().reset_index()
            df_dim['Potencia_kW'] = df_dim['Potencia_Total_Instalada_W'] / 1000
            df_dim['Custo_Demanda_R$'] = df_dim['Demanda_kW'] * tarifa_demanda
            
            st.dataframe(
                df_dim[['Categoria_Macro', 'Potencia_kW', 'Demanda_kW', 'Custo_Demanda_R$']]
                .sort_values('Demanda_kW', ascending=False)
                .style.format({
                    'Potencia_kW': "{:.1f}",
                    'Demanda_kW': "{:.1f}",
                    'Custo_Demanda_R$': "R$ {:,.2f}"
                }),
                use_container_width=True, hide_index=True
            )

    # --- TAB 2: CONSUMO ---
    with tabs[1]:
        c_bar, c_pie = st.columns([2, 1])
        
        with c_bar:
            st.markdown("### Custo por Categoria (R$)")
            df_custo = df_raw.groupby('Categoria_Macro')['Custo_R$'].sum().reset_index().sort_values('Custo_R$', ascending=False)
            fig_b = px.bar(df_custo, x='Categoria_Macro', y='Custo_R$', text='Custo_R$', color='Categoria_Macro')
            fig_b.update_traces(texttemplate='R$ %{y:,.0f}', textposition='outside')
            fig_b.update_layout(yaxis_title="Custo Estimado (R$)", xaxis_title="")
            st.plotly_chart(fig_b, use_container_width=True)
            
        with c_pie:
            st.markdown("### Distribuição (kWh)")
            df_kwh = df_raw.groupby('Categoria_Macro')['Consumo_kWh'].sum().reset_index()
            fig_p = px.pie(df_kwh, values='Consumo_kWh', names='Categoria_Macro', hole=0.4)
            st.plotly_chart(fig_p, use_container_width=True)
        
        st.markdown("#### Top 10 Vilões do Consumo (Equipamentos)")
        df_top = df_raw.groupby('des_nome_generico_equipamento')[['Quant', 'Consumo_kWh', 'Custo_R$']].sum().reset_index()
        st.dataframe(
            df_top.sort_values('Custo_R$', ascending=False).head(10)
            .style.format({'Consumo_kWh': "{:.0f}", 'Custo_R$': "R$ {:,.2f}", 'Quant': "{:.0f}"}),
            use_container_width=True, hide_index=True
        )

    # --- TAB 3: EFICIÊNCIA ---
    with tabs[2]:
        st.subheader("Potencial de Economia (Retrofit & Comportamento)")
        
        # Parâmetros Editáveis
        c_eff1, c_eff2, c_eff3 = st.columns(3)
        with c_eff1:
            red_ilum = st.slider("Economia LED (%)", 30, 70, 50) / 100
        with c_eff2:
            red_ar = st.slider("Economia Inverter/Automat (%)", 20, 60, 35) / 100
        with c_eff3:
            red_ti = st.slider("Economia Standby TI (%)", 10, 50, 20) / 100
            
        # Cálculo de Economia
        def calc_economia(row):
            cat = row['Categoria_Macro']
            custo = row['Custo_R$']
            if cat == 'Iluminação': return custo * red_ilum
            if cat == 'Climatização': return custo * red_ar
            if cat == 'Informática': return custo * red_ti
            return 0.0
            
        df_raw['Economia_Potencial_R$'] = df_raw.apply(calc_economia, axis=1)
        econ_total = df_raw['Economia_Potencial_R$'].sum()
        
        c_res1, c_res2 = st.columns(2)
        c_res1.metric("Economia Mensal Projetada", formatar_br(econ_total, "R$ "), delta="Economia Direta")
        c_res2.metric("Redução na Fatura (%)", f"{(econ_total/fatura_estimada)*100:.1f}%")
        
        st.progress(min((econ_total/fatura_estimada), 1.0))
        st.caption("Barra de progresso rumo à meta de eficiência (Base 100% da fatura)")

    # --- TAB 4: ROI (RESTAURO COMPLETO) ---
    with tabs[3]:
        st.subheader("Simulador de Investimento Inteligente")
        st.markdown("Distribui o orçamento automaticamente focando no **menor Payback**.")
        
        col_input, col_result = st.columns([1, 2])
        
        with col_input:
            orcamento = st.number_input("Orçamento Disponível (CAPEX)", value=100000.0, step=5000.0)
            st.markdown("**Custos Unitários Estimados:**")
            custo_led = st.number_input("Troca p/ LED (un)", value=40.0)
            custo_ac = st.number_input("Troca p/ Inverter (un)", value=3500.0)
            custo_sensor = st.number_input("Automação Sala (un)", value=200.0)
            
        with col_result:
            # Lógica de Priorização: 1. Iluminação (Barato/Alto Retorno) -> 2. Automação -> 3. Ar Condicionado
            
            # Quantitativos
            qtd_luz = df_raw[df_raw['Categoria_Macro'] == 'Iluminação']['Quant'].sum()
            qtd_ar = df_raw[df_raw['Categoria_Macro'] == 'Climatização']['Quant'].sum()
            
            # Passo 1: Trocar todas as lâmpadas?
            custo_total_luz = qtd_luz * custo_led
            if orcamento >= custo_total_luz:
                inv_luz = custo_total_luz
                luz_trocadas = qtd_luz
            else:
                inv_luz = orcamento
                luz_trocadas = int(orcamento // custo_led)
            
            saldo = orcamento - inv_luz
            
            # Passo 2: Trocar Ares Condicionados
            ac_trocados = 0
            inv_ac = 0
            if saldo > 0:
                ac_possiveis = int(saldo // custo_ac)
                ac_trocados = min(ac_possiveis, qtd_ar)
                inv_ac = ac_trocados * custo_ac
                saldo -= inv_ac
                
            # Resultados ROI
            # Economia unitária média baseada na Tab Eficiência
            econ_luz_total = df_raw[df_raw['Categoria_Macro'] == 'Iluminação']['Economia_Potencial_R$'].sum()
            econ_unit_luz = econ_luz_total / qtd_luz if qtd_luz > 0 else 0
            
            econ_ar_total = df_raw[df_raw['Categoria_Macro'] == 'Climatização']['Economia_Potencial_R$'].sum()
            econ_unit_ar = econ_ar_total / qtd_ar if qtd_ar > 0 else 0
            
            retorno_mensal = (luz_trocadas * econ_unit_luz) + (ac_trocados * econ_unit_ar)
            payback = (inv_luz + inv_ac) / retorno_mensal if retorno_mensal > 0 else 999
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Lâmpadas Novas", f"{int(luz_trocadas)}")
            k2.metric("Ares Novos", f"{int(ac_trocados)}")
            k3.metric("Payback Estimado", f"{payback:.1f} meses", delta="Retorno ROI")
            
            if saldo > 0:
                st.info(f"💰 Sobra de Orçamento: {formatar_br(saldo, 'R$ ')}")
            else:
                st.warning("Orçamento Esgotado.")

    # --- TAB 5: DETALHAMENTO (DRILL DOWN) ---
    with tabs[4]:
        col_filtros, col_dados = st.columns([1, 3])
        
        with col_filtros:
            st.markdown("### Filtros")
            setores = ['Todos'] + sorted(df_raw['Setor'].unique().tolist())
            filtro_setor = st.selectbox("Filtrar por Setor:", setores)
            
            andares = ['Todos'] + sorted(df_raw['num_andar'].unique().tolist())
            filtro_andar = st.selectbox("Filtrar por Andar:", andares)
            
            st.markdown("---")
            filtro_termico = st.checkbox("🔥 Apenas Equipamentos Térmicos/Copa", value=False, help="Geladeiras, Microondas, Cafeteiras, etc.")

        with col_dados:
            # Aplicação dos Filtros
            df_filtered = df_raw.copy()
            if filtro_setor != 'Todos':
                df_filtered = df_filtered[df_filtered['Setor'] == filtro_setor]
            if filtro_andar != 'Todos':
                df_filtered = df_filtered[df_filtered['num_andar'] == filtro_andar]
            
            if filtro_termico:
                termicos = ['GELADEIRA', 'MICROONDAS', 'CAFETEIRA', 'CHALEIRA', 'FOGÃO', 'FORNO', 'BEBEDOURO', 'FRIGOBAR']
                mask = df_filtered['des_nome_generico_equipamento'].apply(lambda x: any(t in str(x) for t in termicos))
                df_filtered = df_filtered[mask]
                st.warning(f"Exibindo apenas equipamentos térmicos ({len(df_filtered)} itens).")

            # Agrupamento para exibição
            if filtro_setor == 'Todos' and filtro_andar == 'Todos':
                # Visão Geral por Setor
                st.subheader("Visão Geral por Setor")
                df_view = df_filtered.groupby('Setor')[['Quant', 'Consumo_kWh', 'Custo_R$']].sum().reset_index()
                st.dataframe(
                    df_view.sort_values('Custo_R$', ascending=False).style.format({
                        'Consumo_kWh': "{:.0f}", 'Custo_R$': "R$ {:,.2f}"
                    }), use_container_width=True, hide_index=True
                )
            else:
                # Visão Detalhada por Sala/Equipamento
                st.subheader("Detalhamento Sala a Sala")
                df_view = df_filtered[['Id_sala', 'des_nome_generico_equipamento', 'Quant', 'Potencia_Total_Instalada_W', 'Custo_R$']]
                st.dataframe(
                    df_view.sort_values('Custo_R$', ascending=False).style.format({
                        'Potencia_Total_Instalada_W': "{:.0f} W",
                        'Custo_R$': "R$ {:,.2f}"
                    }), use_container_width=True, hide_index=True
                )
else:
    st.info("Aguardando dados... Se estiver localmente, certifique-se que os arquivos CSV/XLSX estão na mesma pasta.")
