import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia UFRGS", layout="wide", page_icon="⚡")

st.title("⚡ Monitoramento de Eficiência Energética")
st.markdown("""
Este painel consome dados em tempo real do inventário e de ocupação. 
Utilize as abas abaixo para analisar custos, eficiência e demanda de potência (pico).
""")

# --- 1. CARREGAMENTO E TRATAMENTO DE DADOS ---

# URL RAW do arquivo no GitHub (Link direto para o dado bruto)
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
# Link novo para o arquivo Excel de Horários
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/refs/heads/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # --- CARGA INVENTÁRIO ---
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='cp1252', on_bad_lines='skip') 
        df_inv.columns = df_inv.columns.str.strip()
        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)

        # Tratamento de Strings
        if 'num_andar' in df_inv.columns:
            df_inv['num_andar'] = df_inv['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'NaN', ''], 'Não Identificado')
        if 'Id_sala' in df_inv.columns:
            df_inv['Id_sala'] = df_inv['Id_sala'].astype(str).replace(['nan', 'NaN', ''], 'Não Identificado')
        
        # Conversão de Potência
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row['des_potencia']).upper().strip() if pd.notna(row['des_potencia']) else ""
            return p * 0.293 / 3.0 if 'BTU' in u else p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']
        
        # --- CARGA OCUPAÇÃO (EXCEL) ---
        try:
            # Pandas lê Excel direto da URL se tiver a engine 'openpyxl'
            # Lê todas as abas para encontrar a correta
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            
            # Procura aba que tenha colunas de Entrada/Saida
            nome_aba_dados = None
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                # Verifica nomes comuns de colunas
                cols_upper = [c.upper() for c in df_temp.columns]
                if 'ENTRADASAIDA' in cols_upper or 'DATAHORA' in cols_upper or 'HORÁRIO' in cols_upper:
                    nome_aba_dados = aba
                    break
            
            if nome_aba_dados:
                df_oc = pd.read_excel(xls, sheet_name=nome_aba_dados)
            else:
                # Se não achar colunas óbvias, tenta a primeira aba
                df_oc = pd.read_excel(xls, sheet_name=0)

            # Limpeza de colunas (Remove espaços)
            df_oc.columns = df_oc.columns.str.strip()
            
            # Mapeamento de colunas para garantir padrão (DataHora e EntradaSaida)
            # Adapte as chaves deste dicionário se o nome no Excel for diferente (ex: "Horário" -> "DataHora")
            mapa_colunas = {
                'Horário': 'DataHora',
                'Data': 'DataHora',
                'Tipo': 'EntradaSaida',
                'Movimento': 'EntradaSaida'
            }
            df_oc = df_oc.rename(columns=mapa_colunas)

            # Verifica se as colunas essenciais existem após renomear
            if 'DataHora' in df_oc.columns:
                df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
                df_oc = df_oc.dropna(subset=['DataHora'])
                df_oc = df_oc.sort_values('DataHora')
                
                # Cálculo de Ocupação (Entrada +1, Saída -1)
                if 'EntradaSaida' in df_oc.columns:
                    # Mapeia E/S para 1/-1. Ajuste se o Excel usar "Entrada"/"Saída"
                    df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str[0].map({'E': 1, 'S': -1}).fillna(0)
                else:
                    st.warning("Coluna de Entrada/Saída não identificada no Excel.")
                    df_oc['Variacao'] = 0

                df_oc['Ocupacao_Acumulada'] = df_oc['Variacao'].cumsum()
                
                # Remove valores negativos (começa do zero)
                min_val = df_oc['Ocupacao_Acumulada'].min()
                if min_val < 0:
                    df_oc['Ocupacao_Acumulada'] += abs(min_val)
            else:
                st.error("Coluna de Data/Horário não encontrada no Excel.")
                df_oc = pd.DataFrame()
            
        except Exception as e:
            st.warning(f"Não foi possível processar o arquivo Excel de ocupação: {e}")
            df_oc = pd.DataFrame()

        return df_inv, df_oc

    except Exception as e:
        st.error(f"Erro crítico ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

if not df_raw.empty:
    # --- 2. SIDEBAR E PREMISSAS ---
    with st.sidebar:
        st.header("⚙️ Premissas Operacionais")
        st.caption("Versão: 2.1 (Excel de Horários)")
        
        with st.expander("Horas de Uso (Energia)", expanded=False):
            horas_ar = st.slider("Ar Condicionado", 0, 24, 8)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_pc = st.slider("Computadores", 0, 24, 9)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias úteis", value=22)
        
        st.divider()
        st.markdown("⚡ **Contrato de Demanda**")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=0.65)
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=35.00, help="Valor fixo pago pela disponibilidade (Pico)")
        demanda_contratada = st.number_input("Demanda Contratada (kW)", value=300.0)

    # --- 3. CÁLCULOS DE ENERGIA (BASE) ---
    def agrupar_categoria(cat):
        c = str(cat).upper()
        if 'CLIMATIZAÇÃO' in c or 'AR CONDICIONADO' in c: return 'Climatização'
        if 'ILUMINAÇÃO' in c or 'LÂMPADA' in c: return 'Iluminação'
        if 'INFORMÁTICA' in c or 'COMPUTADOR' in c: return 'Informática'
        return 'Outros'

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar_categoria)
    
    # Cálculo simples de consumo para as abas gerais
    def calc_consumo(row):
        cat = row['Categoria_Macro']
        h = horas_ar if cat == 'Climatização' else horas_luz if cat == 'Iluminação' else horas_pc if cat == 'Informática' else horas_outros
        return (row['Potencia_Total_Item_W'] * h * dias_mes) / 1000

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Mensal_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh
    
    # Agrupamentos
    df_dashboard = df_raw.groupby('Categoria_Macro')[['Custo_Mensal_R$', 'Consumo_Mensal_kWh']].sum().reset_index()
    potencia_instalada_total_kw = df_raw['Potencia_Total_Item_W'].sum() / 1000

    # --- 4. CÁLCULOS DE DEMANDA ---
    if not df_ocupacao.empty and 'Ocupacao_Acumulada' in df_ocupacao.columns:
        pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
        if pd.isna(pico_pessoas): pico_pessoas = 0
        
        # Tenta pegar a data do pico, se houver dados
        if len(df_ocupacao) > 0:
            idx_max = df_ocupacao['Ocupacao_Acumulada'].idxmax()
            data_pico = df_ocupacao.loc[idx_max, 'DataHora']
        else:
            data_pico = "N/A"
        
        # Estimativa de Capacidade Total
        total_pcs = df_raw[df_raw['Categoria_Macro'] == 'Informática']['Quant'].sum()
        capacidade_estimada = total_pcs if total_pcs > pico_pessoas else pico_pessoas * 1.2
        if capacidade_estimada == 0: capacidade_estimada = 1 # Evitar div por zero
        
        # Fator de Simultaneidade Estimado
        fator_simultaneidade = (pico_pessoas / capacidade_estimada)
        
        # Demanda Estimada no Pico (kW)
        carga_base = potencia_instalada_total_kw * 0.20
        carga_variavel = potencia_instalada_total_kw * 0.80
        demanda_estimada_pico = carga_base + (carga_variavel * fator_simultaneidade)
    else:
        pico_pessoas = 0
        data_pico = "N/A"
        demanda_estimada_pico = potencia_instalada_total_kw * 0.6 

    # --- 5. VISUALIZAÇÃO ---
    tab1, tab2, tab3, tab4 = st.tabs(["📉 Demanda de Pico (Contrato)", "📊 Visão Geral Consumo", "💡 Eficiência", "🏢 Detalhes"])

    with tab1:
        st.subheader("Análise de Demanda de Potência (kW)")
        st.markdown("""
        A conta de energia inclui o **Consumo (kWh)** e a **Demanda (kW)**. 
        O gráfico abaixo cruza a entrada/saída de pessoas para estimar o momento de maior carga elétrica simultânea.
        """)

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Pico de Ocupação", f"{int(pico_pessoas)} Pessoas", help=f"Registrado em: {data_pico}")
        kpi2.metric("Potência Instalada Total", f"{potencia_instalada_total_kw:,.0f} kW", help="Soma de todos equipamentos do inventário")
        kpi3.metric("Demanda de Pico Estimada", f"{demanda_estimada_pico:,.0f} kW", delta=f"{(demanda_estimada_pico/demanda_contratada)*100:.0f}% do Contrato", delta_color="inverse")
        
        custo_demanda = demanda_contratada * tarifa_kw_demanda
        multa = max(0, (demanda_estimada_pico - demanda_contratada) * tarifa_kw_demanda * 2) 
        kpi4.metric("Custo Fixo Demanda", f"R$ {custo_demanda:,.2f}", delta=f"+ R$ {multa:,.2f} (Risco Multa)" if multa > 0 else "Sem Multa")

        st.divider()

        # Gráfico de Ocupação
        if not df_ocupacao.empty:
            st.markdown("#### 🏃‍♂️ Curva de Ocupação do Prédio")
            fig_oc = px.line(df_ocupacao, x='DataHora', y='Ocupacao_Acumulada', title='Pessoas no Prédio (Acumulado)')
            
            # Adiciona anotação no ponto de pico
            if pico_pessoas > 0:
                fig_oc.add_annotation(x=data_pico, y=pico_pessoas, text=f"Pico: {int(pico_pessoas)}", showarrow=True, arrowhead=1)
                
            fig_oc.update_layout(xaxis_title="Data/Hora", yaxis_title="Nº Pessoas")
            st.plotly_chart(fig_oc, use_container_width=True)
        else:
            st.info("Dados de ocupação não carregados corretamente. Verifique o arquivo Excel.")

        # Gráfico de Comparação de Demanda
        st.markdown("#### ⚡ Demanda Estimada vs. Contratada")
        fig_dem = go.Figure()
        fig_dem.add_trace(go.Bar(x=['Demanda'], y=[demanda_contratada], name='Contratada', marker_color='green'))
        fig_dem.add_trace(go.Bar(x=['Demanda'], y=[demanda_estimada_pico], name='Pico Estimado', marker_color='red' if demanda_estimada_pico > demanda_contratada else 'orange'))
        fig_dem.add_trace(go.Bar(x=['Demanda'], y=[potencia_instalada_total_kw], name='Total Instalado (Risco Teórico)', marker_color='gray', visible='legendonly'))
        fig_dem.update_layout(barmode='group', yaxis_title="Potência (kW)")
        st.plotly_chart(fig_dem, use_container_width=True)

    with tab2:
        st.subheader("Diagnóstico de Consumo (kWh)")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Distribuição de Custos")
            fig_pie = px.pie(df_dashboard, values='Custo_Mensal_R$', names='Categoria_Macro', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with col2:
            st.metric("Total da Fatura (Consumo)", f"R$ {df_dashboard['Custo_Mensal_R$'].sum():,.2f}")
            st.caption("Não inclui o custo de demanda mostrado na Aba 1.")

    with tab3:
        st.subheader("Potencial de Eficiência")
        # Simplificado para o exemplo
        fator_eco = {'Climatização': 0.4, 'Iluminação': 0.6, 'Informática': 0.3, 'Outros': 0}
        df_raw['Eco_R$'] = df_raw.apply(lambda x: x['Custo_Mensal_R$'] * fator_eco.get(x['Categoria_Macro'], 0), axis=1)
        total_eco = df_raw['Eco_R$'].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Economia Potencial Mensal", f"R$ {total_eco:,.2f}")
        c2.progress(int((total_eco / df_dashboard['Custo_Mensal_R$'].sum()) * 100), text="Redução Percentual")
        
        st.info("Considerando: LED (60%), Inverter (40%) e PCs Modernos (30%)")

    with tab4:
        st.subheader("Detalhes por Setor/Andar")
        st.dataframe(df_raw.head(50))

else:
    st.warning("Aguardando dados...")
