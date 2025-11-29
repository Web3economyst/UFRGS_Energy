import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia (Dimensionamento)", layout="wide", page_icon="⚡")

st.title("⚡ Gestão de Energia: Dimensionamento de Demanda")
st.markdown("""
Este painel calcula a **Demanda de Pico Estimada** com base na carga instalada e fatores de simultaneidade. 
O custo financeiro é projetado considerando que o contrato seja ajustado para este pico (Cenário Ideal).
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
    # --- 2. SIDEBAR ---
    with st.sidebar:
        st.header("⚙️ Parâmetros")
        
        st.subheader("💰 Tarifas Locais")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=0.65)
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.00, help="Valor cobrado por kW de potência disponível.")
        
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

    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    
    # --- 4. VISUALIZAÇÃO ---
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📉 Dimensionamento Demanda", 
        "⚡ Consumo (kWh)", 
        "💡 Eficiência & ROI", 
        "🏫 Detalhe Salas"
    ])

    # --- ABA 1: DIMENSIONAMENTO (SEM MULTA) ---
    with tab1:
        st.subheader("Análise de Pico e Dimensionamento de Contrato")
        
        with st.expander("📚 Como interpretamos o Pico?", expanded=False):
            st.markdown(r"""
            Como o valor contratado é desconhecido, este painel calcula o **Cenário Ideal**.
            
            1.  Calculamos o **Pico de Demanda** baseado nos equipamentos e seus fatores de uso simultâneo.
            2.  Assumimos que sua **Demanda Contratada** deveria ser igual a esse Pico.
            3.  O custo exibido é o valor que seria pago mensalmente para manter essa disponibilidade de potência.
            """)

        # KPIs
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Potência Instalada (Total)", f"{total_instalado_kw:,.1f} kW", help="Se ligássemos TUDO ao mesmo tempo")
        
        # O Fator de Demanda Global mostra a eficiência de uso
        fd_global = (total_demanda_pico_kw / total_instalado_kw) * 100 if total_instalado_kw > 0 else 0
        col2.metric("Fator de Demanda Global", f"{fd_global:.1f}%", help="Percentual da carga total que funciona simultaneamente no pico")

        col3.metric("Pico Estimado (Contrato Ideal)", f"{total_demanda_pico_kw:,.1f} kW", help="Demanda máxima provável")
        
        # Custo baseado no Pico (Sem multa, apenas custo de disponibilidade)
        custo_demanda = total_demanda_pico_kw * tarifa_kw_demanda
        col4.metric("Custo Mensal de Demanda", f"R$ {custo_demanda:,.2f}", help=f"Cálculo: {total_demanda_pico_kw:.1f} kW x R$ {tarifa_kw_demanda:.2f}")

        st.divider()

        # Gráfico Gauge: Pico vs Potência Instalada
        c_gauge, c_tbl = st.columns([1, 1.5])
        
        with c_gauge:
            # Gauge comparando o Pico com a Capacidade Total Instalada
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = total_demanda_pico_kw,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "Utilização da Infraestrutura (kW)"},
                gauge = {
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "rgba(31, 119, 180, 0.8)"}, # Azul Padrão
                    'steps': [
                        {'range': [0, total_demanda_pico_kw], 'color': "rgba(0,0,0,0)"}, # Transparente
                        {'range': [total_demanda_pico_kw, total_instalado_kw], 'color': "#f0f2f6"}], # Cinza claro
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': total_demanda_pico_kw}
                }
            ))
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            # Nota sobre transformador
            kVA_calc = total_demanda_pico_kw / 0.92
            st.info(f"Para suportar esse pico de **{total_demanda_pico_kw:.0f} kW**, recomenda-se um transformador/entrada de energia de pelo menos **{kVA_calc:.0f} kVA**.")

        with c_tbl:
            st.markdown("#### Composição do Pico por Categoria")
            df_demanda_cat = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
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
        k2.metric("Custo do Consumo", f"R$ {custo_total_consumo:,.2f}", help="Custo apenas da energia consumida")
        
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
        
        col_input, col_result = st.columns([1, 2])
        
        with col_input:
            st.markdown("##### Parâmetros do Projeto")
            investimento = st.number_input("Verba Disponível (R$)", 50000.0, step=5000.0)
            st.caption("Focando em troca de iluminação (LED) e Ar Condicionado (Inverter).")
        
        with col_result:
            eco_potencial_kwh = (consumo_total_kwh * 0.4 * 0.4) + (consumo_total_kwh * 0.3 * 0.6)
            eco_financeira = eco_potencial_kwh * tarifa_kwh
            payback = investimento / eco_financeira if eco_financeira > 0 else 0
            
            st.markdown("##### Resultados Projetados")
            m1, m2, m3 = st.columns(3)
            m1.metric("Economia Mensal Estimada", f"R$ {eco_financeira:,.2f}")
            m2.metric("Redução de Carga (Alívio Demanda)", f"{total_demanda_pico_kw * 0.15:,.1f} kW", help="Redução estimada no Pico.")
            m3.metric("Payback Simples", f"{payback:.1f} meses")
            
            if payback < 12: st.success("✅ Alta Viabilidade")
            elif payback < 36: st.info("⚠️ Viabilidade Média")
            else: st.warning("❌ Payback Longo")

    # --- ABA 4: DETALHE SALAS ---
    with tab4:
        st.subheader("Consulta por Ambiente")
        sel_sala = st.selectbox("Selecione a Sala:", sorted(df_raw['Id_sala'].unique().astype(str)))
        
        if sel_sala:
            df_s = df_raw[df_raw['Id_sala'] == sel_sala]
            st.dataframe(df_s[['des_nome_equipamento', 'Quant', 'Potencia_Instalada_kW', 'Demanda_Estimada_kW', 'Consumo_Mensal_kWh']])

else:
    st.info("Aguardando dados... Se o erro persistir, verifique a conexão com o GitHub.")
