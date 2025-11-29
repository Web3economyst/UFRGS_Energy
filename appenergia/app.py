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
Agora com suporte a **Salas 24h** e análise dinâmica de demanda baseada no pico de ocupação.
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
            
            if not nome_aba_dados:
                nome_aba_dados = xls.sheet_names[0]

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
                    if min_val < 0:
                        grupo['Ocupacao_Dia'] += abs(min_val)
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
    # --- 2. SIDEBAR E PREMISSAS (COMPLETO) ---
    with st.sidebar:
        st.header("⚙️ Configurações")
        
        # ---------------------------------------------------------
        # NOVO: SELEÇÃO DE SALAS 24H
        # ---------------------------------------------------------
        st.subheader("🕒 Salas de Operação 24h")
        st.caption("Salas selecionadas aqui terão consumo calculado 24h/dia, ignorando os sliders abaixo.")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Selecione as Salas:", lista_salas)
        # ---------------------------------------------------------

        with st.expander("Horas de Uso (Padrão)", expanded=False):
            st.caption("Aplica-se às salas NÃO selecionadas acima")
            horas_ar = st.slider("Ar Condicionado", 0, 24, 8)
            horas_luz = st.slider("Iluminação", 0, 24, 10)
            horas_pc = st.slider("Computadores/TI", 0, 24, 9)
            horas_eletro = st.slider("Eletrodomésticos", 0, 24, 5)
            horas_outros = st.slider("Outros", 0, 24, 6)
            dias_mes = st.number_input("Dias úteis/mês", value=22)
        
        st.divider()
        st.markdown("⚡ **Tarifas**")
        tarifa_kwh = st.number_input("Tarifa Consumo (R$/kWh)", value=0.65)
        # Ajuste: Apenas o custo do kW, sem contrato fixo
        tarifa_kw_demanda = st.number_input("Custo de Demanda Medida (R$/kW)", value=35.00, help="Custo pago pelo pico máximo atingido (kW)")
        
        st.markdown("🌱 **Sustentabilidade**")
        fator_co2 = st.number_input("kg CO2 por kWh", value=0.086, format="%.3f")

    # --- 3. CATEGORIZAÇÃO E CÁLCULOS (COM LÓGICA 24H) ---
    def agrupar_categoria(cat):
        c = str(cat).upper()
        if 'CLIMATIZAÇÃO' in c or 'AR CONDICIONADO' in c: return 'Climatização'
        if 'ILUMINAÇÃO' in c or 'LÂMPADA' in c: return 'Iluminação'
        if 'INFORMÁTICA' in c or 'COMPUTADOR' in c or 'MONITOR' in c: return 'Informática'
        if 'ELETRODOMÉSTICO' in c: return 'Eletrodomésticos'
        return 'Outros'

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar_categoria)
    
    # ---------------------------------------------------------
    # NOVO CÁLCULO DE CONSUMO (LÓGICA 24H)
    # ---------------------------------------------------------
    def calc_consumo(row):
        # 1. Verifica se a sala é 24h
        if str(row['Id_sala']) in salas_24h:
            h = 24
        else:
            # 2. Se não for, usa a lógica padrão dos sliders
            cat = row['Categoria_Macro']
            if cat == 'Climatização': h = horas_ar
            elif cat == 'Iluminação': h = horas_luz
            elif cat == 'Informática': h = horas_pc
            elif cat == 'Eletrodomésticos': h = horas_eletro
            else: h = horas_outros
        
        # Fórmula: (Watts * horas * dias) / 1000
        # Obs: Se for 24h, assumimos 30 dias no mês ou mantemos dias úteis? 
        # Geralmente 24h é servidor que roda fim de semana. Vou fixar 30 dias para salas 24h.
        dias_calculo = 30 if str(row['Id_sala']) in salas_24h else dias_mes
            
        return (row['Potencia_Total_Item_W'] * h * dias_calculo) / 1000

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calc_consumo, axis=1)
    df_raw['Custo_Mensal_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh
    
    # Cálculo de Potência Instalada
    potencia_instalada_total_kw = df_raw['Potencia_Total_Item_W'].sum() / 1000

    # --- 4. CÁLCULO DE DEMANDA DE PICO (BASEADO EM PESSOAS) ---
    if not df_ocupacao.empty and 'Ocupacao_Acumulada' in df_ocupacao.columns:
        pico_pessoas = df_ocupacao['Ocupacao_Acumulada'].max()
        if pd.isna(pico_pessoas): pico_pessoas = 0
        
        if len(df_ocupacao) > 0:
            idx_max = df_ocupacao['Ocupacao_Acumulada'].idxmax()
            data_pico = df_ocupacao.loc[idx_max, 'DataHora']
        else:
            data_pico = "N/A"
        
        # Estimativa de Simultaneidade baseada no pico de pessoas
        total_pcs = df_raw[df_raw['Categoria_Macro'] == 'Informática']['Quant'].sum()
        capacidade_estimada = total_pcs if total_pcs > pico_pessoas else pico_pessoas * 1.2
        if capacidade_estimada == 0: capacidade_estimada = 1
        
        fator_simultaneidade = (pico_pessoas / capacidade_estimada)
        
        # Demanda Estimada: Carga Base (o que fica ligado sempre) + Variável (depende de pessoas)
        # Ajuste: Salas 24h contribuem para a Carga Base
        potencia_salas_24h = df_raw[df_raw['Id_sala'].astype(str).isin(salas_24h)]['Potencia_Total_Item_W'].sum() / 1000
        potencia_resto = potencia_instalada_total_kw - potencia_salas_24h
        
        carga_base = potencia_salas_24h + (potencia_resto * 0.15) # 24h + standbys
        carga_variavel = potencia_resto * 0.85
        
        demanda_estimada_pico = carga_base + (carga_variavel * fator_simultaneidade)
    else:
        pico_pessoas = 0
        data_pico = "Sem dados"
        demanda_estimada_pico = potencia_instalada_total_kw * 0.6 

    # --- 5. CÁLCULO DE ECONOMIA (PROJEÇÃO) ---
    fator_economia = {
        'Climatização': 0.40, 'Iluminação': 0.60, 
        'Informática': 0.30, 'Eletrodomésticos': 0.10, 'Outros': 0.0
    }
    df_raw['Economia_Estimada_R$'] = df_raw.apply(lambda x: x['Custo_Mensal_R$'] * fator_economia.get(x['Categoria_Macro'], 0), axis=1)
    df_raw['Custo_Projetado_R$'] = df_raw['Custo_Mensal_R$'] - df_raw['Economia_Estimada_R$']
    df_raw['Economia_kWh'] = df_raw['Consumo_Mensal_kWh'] * df_raw['Categoria_Macro'].map(fator_economia).fillna(0)

    df_dashboard = df_raw.groupby('Categoria_Macro')[['Custo_Mensal_R$', 'Custo_Projetado_R$', 'Economia_Estimada_R$', 'Consumo_Mensal_kWh', 'Economia_kWh']].sum().reset_index()

    # --- 6. VISUALIZAÇÃO ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📉 Demanda & Ocupação", 
        "📊 Consumo Geral", 
        "💡 Eficiência", 
        "📅 Sazonalidade", 
        "🏢 Salas", 
        "💰 ROI Projeto"
    ])

    # ABA 1: DEMANDA (AJUSTADO)
    with tab1:
        st.subheader("Análise de Demanda pelo Pico de Ocupação")
        
        col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
        col_kpi1.metric("Pico de Pessoas", f"{int(pico_pessoas)}", help=f"Data do evento: {data_pico}")
        col_kpi2.metric("Potência Instalada", f"{potencia_instalada_total_kw:,.0f} kW")
        
        # Demanda calculada pelo comportamento
        col_kpi3.metric("Demanda Máxima Atingida", f"{demanda_estimada_pico:,.0f} kW", help="Baseado na simultaneidade do pico de pessoas + Salas 24h")
        
        # Custo baseado na demanda atingida (sem contrato fixo)
        custo_demanda_medida = demanda_estimada_pico * tarifa_kw_demanda
        col_kpi4.metric("Custo da Demanda", f"R$ {custo_demanda_medida:,.2f}", help=f"Considerando tarifa de R$ {tarifa_kw_demanda}/kW no pico")

        st.divider()
        if not df_ocupacao.empty:
            st.markdown("#### 🏃‍♂️ Fluxo de Ocupação vs Demanda")
            
            # Gráfico de ocupação
            fig_oc = px.line(df_ocupacao, x='DataHora', y='Ocupacao_Acumulada', title='Curva de Ocupação Real')
            if pico_pessoas > 0:
                fig_oc.add_annotation(x=data_pico, y=pico_pessoas, text=f"Pico: {int(pico_pessoas)}", showarrow=True, arrowhead=1)
            st.plotly_chart(fig_oc, use_container_width=True)
        
        # Gráfico comparativo de Cargas
        fig_dem = go.Figure()
        fig_dem.add_trace(go.Bar(x=['Potência'], y=[demanda_estimada_pico], name='Demanda Alcançada', marker_color='orange'))
        fig_dem.add_trace(go.Bar(x=['Potência'], y=[potencia_instalada_total_kw], name='Total Instalado', marker_color='gray', visible='legendonly'))
        
        # Adiciona linha de Salas 24h como referência
        carga_24h = df_raw[df_raw['Id_sala'].astype(str).isin(salas_24h)]['Potencia_Total_Item_W'].sum() / 1000
        if carga_24h > 0:
            fig_dem.add_trace(go.Bar(x=['Potência'], y=[carga_24h], name='Carga Base (24h)', marker_color='red'))
            
        fig_dem.update_layout(title="Composição da Carga Elétrica (kW)")
        st.plotly_chart(fig_dem, use_container_width=True)

    # ABA 2: VISÃO GERAL
    with tab2:
        st.subheader("Consumo e Custos Operacionais")
        custo_total = df_dashboard['Custo_Mensal_R$'].sum()
        consumo_total = df_dashboard['Consumo_Mensal_kWh'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Custo Mensal Estimado", f"R$ {custo_total:,.2f}")
        c2.metric("Consumo Mensal", f"{consumo_total:,.0f} kWh")
        
        # Verifica se há salas 24h para mostrar impacto
        custo_24h = df_raw[df_raw['Id_sala'].astype(str).isin(salas_24h)]['Custo_Mensal_R$'].sum()
        c3.metric("Custo Salas 24h", f"R$ {custo_24h:,.2f}", help="Custo isolado das salas selecionadas como 24h")
        
        st.divider()
        c_g1, c_g2 = st.columns([1, 2])
        with c_g1:
            st.markdown("#### Distribuição de Custos")
            fig_pie = px.pie(df_dashboard, values='Custo_Mensal_R$', names='Categoria_Macro', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c_g2:
            st.markdown("#### Custo por Grupo")
            fig_bar = px.bar(df_dashboard, x='Categoria_Macro', y='Custo_Mensal_R$', color='Categoria_Macro', text_auto='.2s')
            st.plotly_chart(fig_bar, use_container_width=True)

    # ABA 3: EFICIÊNCIA
    with tab3:
        st.subheader("Potencial de Modernização")
        total_eco_rs = df_dashboard['Economia_Estimada_R$'].sum()
        total_eco_kwh = df_dashboard['Economia_kWh'].sum()
        co2_total = total_eco_kwh * fator_co2
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Economia Financeira", f"R$ {total_eco_rs:,.2f}", delta="Mensal")
        k2.metric("Redução de Consumo", f"{total_eco_kwh:,.0f} kWh", delta="Mensal")
        k3.metric("Pegada de Carbono", f"{co2_total:.1f} kg CO2", delta="Evitado/Mês")
        
        st.divider()
        fig_comp = go.Figure()
        fig_comp.add_trace(go.Bar(x=df_dashboard['Categoria_Macro'], y=df_dashboard['Custo_Mensal_R$'], name='Atual', marker_color='#EF553B'))
        fig_comp.add_trace(go.Bar(x=df_dashboard['Categoria_Macro'], y=df_dashboard['Custo_Projetado_R$'], name='Eficiente', marker_color='#00CC96'))
        st.plotly_chart(fig_comp, use_container_width=True)

    # ABA 4: SAZONALIDADE
    with tab4:
        st.subheader("Projeção Anual")
        sazonalidade = {'Jan': 1.2, 'Fev': 1.2, 'Mar': 1.1, 'Abr': 0.8, 'Mai': 0.6, 'Jun': 0.9, 'Jul': 1.0, 'Ago': 0.9, 'Set': 0.7, 'Out': 0.9, 'Nov': 1.1, 'Dez': 1.2}
        
        custo_ar = df_raw[df_raw['Categoria_Macro']=='Climatização']['Custo_Mensal_R$'].sum()
        custo_base = custo_total - custo_ar
        
        dados = []
        for m, f in sazonalidade.items():
            dados.append({'Mês': m, 'Custo': (custo_ar * f) + custo_base})
            
        fig_saz = px.line(pd.DataFrame(dados), x='Mês', y='Custo', markers=True, title='Variação Estimada do Custo')
        st.plotly_chart(fig_saz, use_container_width=True)

    # ABA 5: DETALHES (Andar/Sala)
    with tab5:
        st.subheader("Detalhamento por Sala")
        
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            salas = sorted(df_raw['Id_sala'].unique().astype(str))
            sel_sala = st.selectbox("Selecione uma Sala:", salas)
        
        if sel_sala:
            df_s = df_raw[df_raw['Id_sala'] == sel_sala]
            custo_sala_total = df_s['Custo_Mensal_R$'].sum()
            
            # Indicador se é 24h
            is_24h = sel_sala in salas_24h
            status_sala = "🔴 Operação 24h" if is_24h else "🟢 Horário Comercial"
            
            st.markdown(f"#### {sel_sala} - {status_sala}")
            st.metric("Fatura Mensal da Sala", f"R$ {custo_sala_total:,.2f}")
            
            st.dataframe(df_s[['des_nome_equipamento', 'Quant', 'num_potencia', 'Custo_Mensal_R$']].sort_values('Custo_Mensal_R$', ascending=False), use_container_width=True)

    # ABA 6: VIABILIDADE (ROI)
    with tab6:
        st.subheader("Simulador de Projeto (ROI)")
        
        col_proj1, col_proj2 = st.columns(2)
        
        with col_proj1:
            st.markdown("#### 🎯 Meta de Investimento")
            meta_invest = st.number_input("Verba Disponível (R$)", value=100000.0, step=5000.0)
            
        with col_proj2:
            st.markdown("#### 💰 Custos Unitários")
            inv_lampada = st.number_input("Lâmpada LED (R$)", 25.0)
            inv_ac = st.number_input("Ar Inverter (R$)", 3500.0)
            inv_pc = st.number_input("Mini Computadores (R$)", 2800.0)

        st.divider()
        
        # Algoritmo de Priorização ROI
        # 1. Luz
        qtd_lamp_total = df_raw[df_raw['Categoria_Macro']=='Iluminação']['Quant'].sum()
        max_inv_luz = qtd_lamp_total * inv_lampada
        investido_luz = min(meta_invest, max_inv_luz)
        sobra_1 = meta_invest - investido_luz
        luzes_trocadas = int(investido_luz / inv_lampada)
        
        # 2. Ar
        qtd_ac_total = df_raw[df_raw['Categoria_Macro']=='Climatização']['Quant'].sum()
        max_inv_ac = qtd_ac_total * inv_ac
        investido_ac = min(sobra_1, max_inv_ac)
        sobra_2 = sobra_1 - investido_ac
        acs_trocados = int(investido_ac / inv_ac)
        
        # 3. PC
        qtd_pc_total = df_raw[df_raw['Categoria_Macro']=='Informática']['Quant'].sum()
        max_inv_pc = qtd_pc_total * inv_pc
        investido_pc = min(sobra_2, max_inv_pc)
        pcs_trocados = int(investido_pc / inv_pc)
        
        st.markdown(f"**Sugestão de Alocação para R$ {meta_invest:,.2f}:**")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Lâmpadas", f"{luzes_trocadas} un.")
        k2.metric("Ares Cond.", f"{acs_trocados} un.")
        k3.metric("Computadores", f"{pcs_trocados} un.")
        
        eco_luz = luzes_trocadas * (0.030 * 10 * 22 * tarifa_kwh * 0.6) 
        eco_ac = acs_trocados * (1.4 * 8 * 22 * tarifa_kwh * 0.4)
        eco_pc = pcs_trocados * (0.115 * 9 * 22 * tarifa_kwh)
        
        eco_total_proj = eco_luz + eco_ac + eco_pc
        payback_proj = meta_invest / eco_total_proj if eco_total_proj > 0 else 0
        k4.metric("Payback Estimado", f"{payback_proj:.1f} meses")

else:
    st.warning("Aguardando carregamento dos dados...")
