import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import unicodedata

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia UFRGS", layout="wide", page_icon="⚡")

st.title("⚡ Monitoramento de Eficiência Energética")
st.markdown("""
Este painel consome dados em tempo real do inventário e de ocupação hospedados no GitHub. 
Ele integra análise de consumo, viabilidade financeira e monitoramento de demanda de pico.
""")

# --- 1. CARREGAMENTO E TRATAMENTO DE DADOS ---

# URLs Diretas (RAW Content) para garantir download correto
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Hor%C3%A1rios.xlsx"

# Função auxiliar para normalizar texto (remove acentos e caixa alta)
def normalizar_texto(texto):
    if not isinstance(texto, str): return str(texto)
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').upper().strip()

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
            
            # Procura aba correta normalizando nomes
            nome_aba_dados = None
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                cols_norm = [normalizar_texto(c) for c in df_temp.columns]
                # Verifica palavras chave: ENTRADASAIDA, DATAHORA
                if any(x in cols_norm for x in ['ENTRADASAIDA', 'DATAHORA', 'HORARIO', 'TIPO']):
                    nome_aba_dados = aba
                    break
            
            df_oc = pd.read_excel(xls, sheet_name=nome_aba_dados if nome_aba_dados else 0)
            
            # Limpeza de colunas
            df_oc = df_oc.loc[:, ~df_oc.columns.duplicated()]
            
            # Mapeamento de colunas flexível (Normalizado)
            col_data = next((c for c in df_oc.columns if normalizar_texto(c) in ['DATAHORA', 'HORARIO', 'DATA', 'DATA_HORA']), None)
            col_mov = next((c for c in df_oc.columns if normalizar_texto(c) in ['ENTRADASAIDA', 'TIPO', 'MOVIMENTO', 'ENTRADA_SAIDA']), None)

            if col_data:
                df_oc = df_oc.rename(columns={col_data: 'DataHora'})
                if col_mov: df_oc = df_oc.rename(columns={col_mov: 'EntradaSaida'})
                
                df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
                df_oc = df_oc.dropna(subset=['DataHora']).sort_values('DataHora')
                df_oc = df_oc.reset_index(drop=True)
                
                # Tratamento de Movimento
                if 'EntradaSaida' in df_oc.columns:
                    # Pega a primeira letra (E ou S), normaliza e mapeia
                    df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).apply(lambda x: normalizar_texto(x)[0] if len(x)>0 else '').map({'E': 1, 'S': -1}).fillna(0)
                else:
                    df_oc['Variacao'] = 0 # Sem dados de movimento, assume 0

                # Cálculo Diário
                df_oc['Data_Dia'] = df_oc['DataHora'].dt.date
                
                def calcular_saldo_diario(grupo):
                    grupo = grupo.sort_values('DataHora')
                    grupo['Ocupacao_Dia'] = grupo['Variacao'].cumsum()
                    min_val = grupo['Ocupacao_Dia'].min()
                    if min_val < 0: grupo['Ocupacao_Dia'] += abs(min_val)
                    return grupo

                if not df_oc.empty:
                    df_oc = df_oc.groupby('Data_Dia', group_keys=False).apply(calcular_saldo_diario)
                    df_oc['Ocupacao_Acumulada'] = df_oc['Ocupacao_Dia']
            else:
                df_oc = pd.DataFrame()
            
        except Exception as e:
            # print(e) # Debug local
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
        st.caption("Versão: 3.9 (Fix URL + Pico 24h)")
        
        with st.expander("Horas de Uso (Padrão)", expanded=True):
            horas_ar = st.slider("Ar Condicionado", 0, 24, 8)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_pc = st.slider("Computadores/TI", 0, 24, 9)
            horas_eletro = st.slider("Eletrodomésticos", 0, 24, 5)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias úteis/mês", value=22)
        
        st.divider()
        st.markdown("🕒 **Exceções de Horário (24h)**")
        lista_salas_unicas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect(
            "Selecione salas que operam 24h (ex: Servidores, Segurança):",
            options=lista_salas_unicas,
            help="Equipamentos nestas salas entrarão na Carga Base (Pico) e terão consumo de 24h."
        )

        st.divider()
        st.markdown("⚡ **Tarifas e Contrato**")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=0.65)
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=35.00)
        demanda_contratada = st.number_input("Demanda Contratada (kW)", value=300.0)
        
        st.markdown("🌱 **Sustentabilidade**")
        fator_co2 = st.number_input("kg CO2 por kWh", value=0.086, format="%.3f")

    # --- 3. CÁLCULOS PRINCIPAIS ---
    def agrupar_categoria(cat):
        c = str(cat).upper()
        if 'CLIMATIZAÇÃO' in c or 'AR CONDICIONADO' in c: return 'Climatização'
        if 'ILUMINAÇÃO' in c or 'LÂMPADA' in c: return 'Iluminação'
        if 'INFORMÁTICA' in c or 'COMPUTADOR' in c or 'MONITOR' in c: return 'Informática'
        if 'ELETRODOMÉSTICO' in c: return 'Eletrodomésticos'
        return 'Outros'

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar_categoria)
    
    # Consumo Mensal (Considerando Salas 24h)
    def calc_consumo(row):
        if str(row['Id_sala']) in salas_24h:
            h = 24
        else:
            cat = row['Categoria_Macro']
            if cat == 'Climatização': h = horas_ar
            elif cat == 'Iluminação': h = horas_luz
            elif cat == 'Informática': h = horas_pc
            elif cat == 'Eletrodomésticos': h = horas_eletro
            else: h = horas_outros
        return (row['Potencia_Total_Item_W'] * h * dias_mes) / 1000

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Mensal_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh
    
    # --- 4. CÁLCULO DE DEMANDA DE PICO (REFINADO) ---
    # Separa carga das salas 24h (Carga Base Garantida)
    potencia_salas_24h_kw = df_raw[df_raw['Id_sala'].isin(salas_24h)]['Potencia_Total_Item_W'].sum() / 1000
    # Potência do restante do prédio
    potencia_resto_kw = (df_raw['Potencia_Total_Item_W'].sum() / 1000) - potencia_salas_24h_kw
    
    if not df_ocupacao.empty and 'Ocupacao_Acumulada' in df_ocupacao.columns:
        pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
        if pd.isna(pico_pessoas): pico_pessoas = 0
        
        if len(df_ocupacao) > 0:
            idx_max = df_ocupacao['Ocupacao_Acumulada'].idxmax()
            data_pico = df_ocupacao.loc[idx_max, 'DataHora']
        else:
            data_pico = "N/A"
        
        # Fator de Simultaneidade para o resto do prédio
        total_pcs = df_raw[df_raw['Categoria_Macro'] == 'Informática']['Quant'].sum()
        capacidade_estimada = max(total_pcs, pico_pessoas * 1.1, 1)
        fator_simultaneidade = (pico_pessoas / capacidade_estimada)
        
        # Demanda = Carga 24h (100%) + Carga Resto (Standby 15% + Uso Variável)
        carga_base_tecnica = potencia_resto_kw * 0.15 # Standby de equipamentos não-24h
        carga_variavel = potencia_resto_kw * 0.85 * fator_simultaneidade
        
        demanda_estimada_pico = potencia_salas_24h_kw + carga_base_tecnica + carga_variavel
    else:
        # Fallback sem arquivo de ocupação
        pico_pessoas = 0
        data_pico = "Sem dados"
        # Assume Carga 24h + 50% do resto
        demanda_estimada_pico = potencia_salas_24h_kw + (potencia_resto_kw * 0.5)

    # --- 5. VISUALIZAÇÃO ---
    
    # Agrupamento para gráficos
    df_dashboard = df_raw.groupby('Categoria_Macro')[['Custo_Mensal_R$', 'Consumo_Mensal_kWh']].sum().reset_index()
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📉 Demanda de Pico", 
        "📊 Visão Geral Consumo", 
        "💡 Potencial Eficiência", 
        "📅 Sazonalidade", 
        "🏢 Detalhes (Andar/Sala)", 
        "💰 Viabilidade"
    ])

    with tab1:
        st.subheader("Análise de Demanda de Potência (kW)")
        st.markdown(f"""
        Estimativa do pico de carga elétrica. 
        **Salas 24h selecionadas:** {len(salas_24h)} (Carga Base Adicional: {potencia_salas_24h_kw:.1f} kW)
        """)
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Pico de Pessoas", f"{int(pico_pessoas)}", help=f"Data: {data_pico}")
        k2.metric("Potência Instalada", f"{(potencia_resto_kw + potencia_salas_24h_kw):,.0f} kW")
        k3.metric("Demanda Estimada", f"{demanda_estimada_pico:,.0f} kW", delta=f"{(demanda_estimada_pico/demanda_contratada)*100:.0f}% do Contrato", delta_color="inverse")
        
        custo_dem = demanda_contratada * tarifa_kw_demanda
        multa = max(0, (demanda_estimada_pico - demanda_contratada) * tarifa_kw_demanda * 2)
        k4.metric("Custo Demanda", f"R$ {custo_dem:,.2f}", delta=f"+ R$ {multa:,.2f} (Multa)" if multa > 0 else "OK")

        st.divider()
        if not df_ocupacao.empty:
            fig_oc = px.line(df_ocupacao, x='DataHora', y='Ocupacao_Acumulada', title='Curva de Ocupação Real')
            if pico_pessoas > 0: fig_oc.add_annotation(x=data_pico, y=pico_pessoas, text="Pico", showarrow=True)
            st.plotly_chart(fig_oc, use_container_width=True)
        else:
            st.warning("Arquivo de horários não carregado. O cálculo de demanda está usando uma estimativa genérica (50% de simultaneidade para salas não-24h).")

        fig_dem = go.Figure()
        fig_dem.add_trace(go.Bar(x=['kW'], y=[demanda_contratada], name='Contratada', marker_color='green'))
        fig_dem.add_trace(go.Bar(x=['kW'], y=[potencia_salas_24h_kw], name='Carga Base (Salas 24h)', marker_color='blue'))
        fig_dem.add_trace(go.Bar(x=['kW'], y=[demanda_estimada_pico - potencia_salas_24h_kw], name='Carga Variável (Pessoas)', marker_color='orange'))
        fig_dem.update_layout(barmode='stack', title="Composição da Demanda Estimada")
        st.plotly_chart(fig_dem, use_container_width=True)

    with tab2:
        st.subheader("Diagnóstico Operacional")
        total_custo = df_dashboard['Custo_Mensal_R$'].sum()
        c1, c2 = st.columns(2)
        c1.metric("Fatura Mensal (Estimada)", f"R$ {total_custo:,.2f}")
        c2.metric("Consumo Mensal", f"{df_dashboard['Consumo_Mensal_kWh'].sum():,.0f} kWh")
        
        c_g1, c_g2 = st.columns(2)
        with c_g1: st.plotly_chart(px.pie(df_dashboard, values='Custo_Mensal_R$', names='Categoria_Macro', title="Custos por Categoria"), use_container_width=True)
        with c_g2: st.plotly_chart(px.bar(df_dashboard, x='Categoria_Macro', y='Custo_Mensal_R$', color='Categoria_Macro', title="Ranking de Custos"), use_container_width=True)

    with tab3:
        st.subheader("Potencial de Modernização")
        # Recalcula economia
        fator_eco = {'Climatização': 0.4, 'Iluminação': 0.6, 'Informática': 0.3, 'Eletrodomésticos': 0.1, 'Outros': 0.0}
        df_raw['Eco_R$'] = df_raw.apply(lambda x: x['Custo_Mensal_R$'] * fator_eco.get(x['Categoria_Macro'], 0), axis=1)
        
        eco_total = df_raw['Eco_R$'].sum()
        novo_custo = total_custo - eco_total
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Economia Potencial", f"R$ {eco_total:,.2f}", delta="Mensal")
        k2.metric("Novo Custo Estimado", f"R$ {novo_custo:,.2f}", delta_color="inverse")
        k3.metric("CO2 Evitado", f"{(df_raw['Eco_R$'].sum()/tarifa_kwh * fator_co2):,.1f} kg", delta="Mensal")
        
        fig_eco = go.Figure()
        fig_eco.add_trace(go.Bar(x=['Custo'], y=[total_custo], name='Atual', marker_color='indianred'))
        fig_eco.add_trace(go.Bar(x=['Custo'], y=[novo_custo], name='Eficiente', marker_color='lightgreen'))
        st.plotly_chart(fig_eco, use_container_width=True)

    with tab4:
        st.subheader("Sazonalidade")
        sazonalidade = {'Jan': 1.2, 'Fev': 1.2, 'Mar': 1.1, 'Abr': 0.8, 'Mai': 0.6, 'Jun': 0.9, 'Jul': 1.0, 'Ago': 0.9, 'Set': 0.7, 'Out': 0.9, 'Nov': 1.1, 'Dez': 1.2}
        custo_ar = df_raw[df_raw['Categoria_Macro']=='Climatização']['Custo_Mensal_R$'].sum()
        custo_base = total_custo - custo_ar
        
        dados_saz = [{'Mês': m, 'Custo': (custo_ar * f) + custo_base} for m, f in sazonalidade.items()]
        st.plotly_chart(px.line(pd.DataFrame(dados_saz), x='Mês', y='Custo', title="Variação Anual Estimada"), use_container_width=True)

    with tab5:
        st.subheader("Detalhamento")
        salas = sorted(df_raw['Id_sala'].unique().astype(str))
        sel = st.selectbox("Selecione Sala:", salas)
        if sel:
            d_s = df_raw[df_raw['Id_sala'] == sel]
            st.metric(f"Custo Mensal - {sel}", f"R$ {d_s['Custo_Mensal_R$'].sum():,.2f}")
            st.dataframe(d_s[['des_nome_equipamento', 'Quant', 'num_potencia', 'Custo_Mensal_R$']].sort_values('Custo_Mensal_R$', ascending=False))

    with tab6:
        st.subheader("Simulador de Projeto (ROI)")
        c1, c2 = st.columns(2)
        invest = c1.number_input("Investimento Disponível (R$)", value=100000.0, step=5000.0)
        
        custo_led = c2.number_input("Custo LED (R$)", 25.0)
        custo_inv = c2.number_input("Custo Ar Inverter (R$)", 3500.0)
        custo_pc = c2.number_input("Custo Mini PC (R$)", 2800.0)
        
        # Lógica de distribuição (Prioridade ROI)
        # 1. Luz
        q_luz = df_raw[df_raw['Categoria_Macro']=='Iluminação']['Quant'].sum()
        $luz = min(invest, q_luz * custo_led)
        rest1 = invest - $luz
        n_luz = int($luz / custo_led)
        
        # 2. Ar
        q_ar = df_raw[df_raw['Categoria_Macro']=='Climatização']['Quant'].sum()
        $ar = min(rest1, q_ar * custo_inv)
        rest2 = rest1 - $ar
        n_ar = int($ar / custo_inv)
        
        # 3. PC
        q_pc = df_raw[df_raw['Categoria_Macro']=='Informática']['Quant'].sum()
        $pc = min(rest2, q_pc * custo_pc)
        n_pc = int($pc / custo_pc)
        
        st.info(f"Plano Sugerido: {n_luz} Lâmpadas + {n_ar} Ares + {n_pc} PCs")
        
        # Payback
        eco_l = n_luz * (0.018 * 10 * 22 * tarifa_kwh) # Exemplo de eco unitária
        eco_a = n_ar * (0.600 * 8 * 22 * tarifa_kwh)
        eco_p = n_pc * (0.100 * 9 * 22 * tarifa_kwh)
        total_eco_mes = eco_l + eco_a + eco_p
        
        if total_eco_mes > 0:
            payback = invest / total_eco_mes
            st.metric("Payback Estimado", f"{payback:.1f} meses")
        else:
            st.warning("Investimento insuficiente para gerar economia.")

else:
    st.warning("Aguardando dados...")
