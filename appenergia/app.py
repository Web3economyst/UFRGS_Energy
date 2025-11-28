import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard de Energia UFRGS", layout="wide", page_icon="⚡")

st.title("⚡ Monitoramento de Eficiência Energética")
st.markdown("""
Este painel consome dados em tempo real do inventário hospedado no GitHub. 
Ele processa o consumo estimado e projeta economias com base na modernização dos equipamentos, focando em três pilares principais:

* **⚡ Iluminação (LED + Sensores):** Substituição de lâmpadas fluorescentes por tecnologia LED e instalação de sensores de presença em áreas de circulação.
* **❄️ Climatização (Inverter + Isolamento):** Troca de aparelhos de ar-condicionado antigos (Janela/On-Off) por modelos Inverter mais eficientes e melhorias no isolamento térmico.
* **💻 Modernização de Equipamentos:** Renovação do parque tecnológico (substituição de CPUs antigas por Mini PCs) e troca de eletrodomésticos ineficientes.
""")

# --- 1. CARREGAMENTO E TRATAMENTO DE DADOS ---

# URL RAW do arquivo no GitHub (Link direto para o dado bruto)
DATA_URL = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"

@st.cache_data
def load_and_process_data():
    try:
        # Tenta ler o CSV especificando encoding 'cp1252' (Padrão Excel/Windows Brasil)
        df = pd.read_csv(DATA_URL, encoding='cp1252', on_bad_lines='skip') 
        
        # Limpeza básica de nomes de colunas (remover espaços extras)
        df.columns = df.columns.str.strip()
        
        # Garantir que Quantidade é número
        df['Quant'] = pd.to_numeric(df['Quant'], errors='coerce').fillna(1)
        
        # Garantir que Potência é número (tratando possíveis textos)
        df['num_potencia'] = pd.to_numeric(df['num_potencia'], errors='coerce').fillna(0)

        # Tratamento da coluna de Andar (Limpeza)
        if 'num_andar' in df.columns:
            # Converte para string, remove decimais (.0) e preenche vazios
            df['num_andar'] = df['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df['num_andar'] = 'Não Identificado'

        # Tratamento da coluna de Sala (Limpeza)
        if 'Id_sala' in df.columns:
            df['Id_sala'] = df['Id_sala'].astype(str).replace(['nan', 'NaN', ''], 'Não Identificado')
        else:
            df['Id_sala'] = 'Não Identificado'
        
        # --- LÓGICA DE CONVERSÃO DE POTÊNCIA ---
        def converter_para_watts(row):
            potencia = row['num_potencia']
            # Garante que é string antes de chamar .upper()
            unidade = str(row['des_potencia']).upper().strip() if pd.notna(row['des_potencia']) else ""
            
            if 'BTU' in unidade:
                # Conversão estimada de capacidade térmica para potência elétrica (W)
                # Considerando equipamentos antigos (COP ~3.0)
                return potencia * 0.293 / 3.0 
            else:
                return potencia

        df['Potencia_Real_W'] = df.apply(converter_para_watts, axis=1)
        
        # Cálculo da Potência Total do Item (Unitário * Quantidade)
        df['Potencia_Total_Item_W'] = df['Potencia_Real_W'] * df['Quant']
        
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados do GitHub: {e}")
        return pd.DataFrame()

df_raw = load_and_process_data()

if not df_raw.empty:
    # --- 2. PREMISSAS DE CÁLCULO (INTERATIVAS) ---
    with st.sidebar:
        st.header("⚙️ Premissas de Cálculo")
        st.caption("Versão: 1.7 (Seletor de Sala)")
        st.markdown("Ajuste as horas de uso para refinar a estimativa mensal.")
        
        horas_ar = st.slider("Horas/Dia - Ar Condicionado", 0, 24, 8)
        horas_luz = st.slider("Horas/Dia - Iluminação", 0, 24, 10)
        horas_pc = st.slider("Horas/Dia - Computadores", 0, 24, 9)
        dias_mes = st.number_input("Dias úteis por mês", value=22)
        tarifa_kwh = st.number_input("Tarifa de Energia (R$/kWh)", value=0.90)
        
        st.divider()
        st.markdown("🌱 **Fator de Emissão CO2**")
        fator_co2 = st.number_input("kg CO2 por kWh (Méd. BR)", value=0.086, format="%.3f")

    # --- 3. CATEGORIZAÇÃO E CÁLCULOS ---
    def agrupar_categoria(cat_original):
        cat = str(cat_original).upper()
        if 'CLIMATIZAÇÃO' in cat or 'AR CONDICIONADO' in cat: return 'Climatização'
        if 'ILUMINAÇÃO' in cat or 'LÂMPADA' in cat: return 'Iluminação'
        if 'INFORMÁTICA' in cat or 'COMPUTADOR' in cat or 'MONITOR' in cat: return 'Informática'
        if 'ELETRODOMÉSTICO' in cat: return 'Eletrodomésticos'
        return 'Outros'

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar_categoria)

    # Calculando Consumo Mensal (kWh) com base nas premissas
    def calcular_kwh_mensal(row):
        cat = row['Categoria_Macro']
        watts_total = row['Potencia_Total_Item_W']
        
        if cat == 'Climatização': horas = horas_ar
        elif cat == 'Iluminação': horas = horas_luz
        elif cat == 'Informática': horas = horas_pc
        else: horas = 4 # média para outros
        
        # (Watts * horas * dias) / 1000
        return (watts_total * horas * dias_mes) / 1000

    df_raw['Consumo_Mensal_kWh'] = df_raw.apply(calcular_kwh_mensal, axis=1)
    df_raw['Custo_Mensal_R$'] = df_raw['Consumo_Mensal_kWh'] * tarifa_kwh

    # --- 4. CÁLCULO DE ECONOMIA (CENÁRIOS) ---
    fator_economia = {
        'Climatização': 0.40,  # 40% (Inverter + Isolamento)
        'Iluminação': 0.60,    # 60% (LED + Sensores)
        'Informática': 0.30,   # 30% (Modernização)
        'Eletrodomésticos': 0.10,
        'Outros': 0.0
    }

    df_raw['Economia_Estimada_R$'] = df_raw.apply(lambda x: x['Custo_Mensal_R$'] * fator_economia.get(x['Categoria_Macro'], 0), axis=1)
    df_raw['Custo_Projetado_R$'] = df_raw['Custo_Mensal_R$'] - df_raw['Economia_Estimada_R$']
    df_raw['Economia_kWh'] = df_raw['Consumo_Mensal_kWh'] * df_raw['Categoria_Macro'].map(fator_economia).fillna(0)

    # Agrupando dados para o Dashboard
    df_dashboard = df_raw.groupby('Categoria_Macro')[['Custo_Mensal_R$', 'Custo_Projetado_R$', 'Economia_Estimada_R$', 'Consumo_Mensal_kWh', 'Economia_kWh']].sum().reset_index()

    # --- 5. VISUALIZAÇÃO NO STREAMLIT ---

    # KPIs do Topo
    total_custo = df_dashboard['Custo_Mensal_R$'].sum()
    total_economia = df_dashboard['Economia_Estimada_R$'].sum()
    total_novo = df_dashboard['Custo_Projetado_R$'].sum()
    
    # KPIs Ambientais
    total_economia_kwh = df_dashboard['Economia_kWh'].sum()
    co2_evitado_kg = total_economia_kwh * fator_co2
    arvores_equivalentes = int(co2_evitado_kg / 15) # Estimativa: 1 árvore absorve ~15kg CO2/ano

    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    col_kpi1.metric("Fatura Mensal (Atual)", f"R$ {total_custo:,.2f}")
    col_kpi2.metric("Economia Estimada", f"R$ {total_economia:,.2f}", delta="42%")
    col_kpi3.metric("CO2 Evitado (Mensal)", f"{co2_evitado_kg:.1f} kg", delta="Sustentabilidade")
    col_kpi4.metric("Árvores Salvas (Eq.)", f"{arvores_equivalentes} árvores", help="Equivalente em árvores plantadas para absorver esse CO2 em 1 ano.")

    st.divider()
    
    # --- ABAS PARA ORGANIZAR O CONTEÚDO ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão Geral", "📅 Sazonalidade (Anual)", "🏢 Detalhes (Andar/Sala)", "💰 Viabilidade Financeira"])

    with tab1:
        # Gráficos Principais
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.subheader("Distribuição de Custos por Tipo")
            fig_pie = px.pie(df_dashboard, values='Custo_Mensal_R$', names='Categoria_Macro', 
                             hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_chart2:
            st.subheader("Comparativo de Economia por Setor")
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(x=df_dashboard['Categoria_Macro'], y=df_dashboard['Custo_Mensal_R$'], name='Custo Atual', marker_color='#EF553B'))
            fig_bar.add_trace(go.Bar(x=df_dashboard['Categoria_Macro'], y=df_dashboard['Custo_Projetado_R$'], name='Custo Otimizado', marker_color='#00CC96'))
            fig_bar.update_layout(barmode='group', xaxis_title="Categoria", yaxis_title="Custo (R$)")
            st.plotly_chart(fig_bar, use_container_width=True)

    with tab2:
        st.subheader("📅 Projeção de Consumo Anual (Sazonalidade)")
        st.markdown("""
        Esta simulação considera que o uso do **Ar Condicionado** varia ao longo do ano.
        * **Verão (Dez-Mar):** Uso intenso (Fator 1.2x).
        * **Inverno (Jun-Ago):** Uso médio/alto para aquecimento (Fator 1.0x).
        * **Meia-estação:** Uso reduzido (Fator 0.6x - 0.8x).
        """)
        
        # Fatores de Sazonalidade Estimados para Porto Alegre (UFRGS)
        sazonalidade_poa = {
            'Jan': 1.2, 'Fev': 1.2, 'Mar': 1.1, 'Abr': 0.8,
            'Mai': 0.6, 'Jun': 0.9, 'Jul': 1.0, 'Ago': 0.9,
            'Set': 0.7, 'Out': 0.9, 'Nov': 1.1, 'Dez': 1.2
        }
        
        # Separar custos base (Ar vs Outros)
        custo_base_ar = df_raw[df_raw['Categoria_Macro'] == 'Climatização']['Custo_Mensal_R$'].sum()
        custo_base_outros = df_raw[df_raw['Categoria_Macro'] != 'Climatização']['Custo_Mensal_R$'].sum()
        
        custo_proj_ar = df_raw[df_raw['Categoria_Macro'] == 'Climatização']['Custo_Projetado_R$'].sum()
        custo_proj_outros = df_raw[df_raw['Categoria_Macro'] != 'Climatização']['Custo_Projetado_R$'].sum()
        
        dados_sazonais = []
        for mes, fator in sazonalidade_poa.items():
            # Custo Atual
            total_atual = (custo_base_ar * fator) + custo_base_outros
            dados_sazonais.append({'Mês': mes, 'Cenário': 'Custo Atual', 'Valor (R$)': total_atual})
            
            # Custo Projetado (Com economia)
            total_proj = (custo_proj_ar * fator) + custo_proj_outros
            dados_sazonais.append({'Mês': mes, 'Cenário': 'Custo Otimizado', 'Valor (R$)': total_proj})
            
        df_sazonal = pd.DataFrame(dados_sazonais)
        
        fig_line = px.line(df_sazonal, x='Mês', y='Valor (R$)', color='Cenário', markers=True,
                           color_discrete_map={'Custo Atual': '#EF553B', 'Custo Otimizado': '#00CC96'})
        fig_line.update_layout(yaxis_title="Custo Estimado (R$)", hovermode="x unified")
        st.plotly_chart(fig_line, use_container_width=True)
        
        custo_anual_atual = df_sazonal[df_sazonal['Cenário']=='Custo Atual']['Valor (R$)'].sum()
        custo_anual_proj = df_sazonal[df_sazonal['Cenário']=='Custo Otimizado']['Valor (R$)'].sum()
        st.info(f"💰 **Economia Anual Projetada:** R$ {(custo_anual_atual - custo_anual_proj):,.2f}")

    with tab3:
        # VISUALIZAÇÃO POR ANDAR
        st.subheader("🏢 Análise de Custo por Andar")
        
        # Agrupa por andar e ordena
        df_andar = df_raw.groupby('num_andar')[['Custo_Mensal_R$']].sum().reset_index()
        
        # Tenta ordenar numericamente se possível, senão alfabeticamente
        try:
            df_andar['sort_key'] = pd.to_numeric(df_andar['num_andar'])
            df_andar = df_andar.sort_values('sort_key')
        except:
            df_andar = df_andar.sort_values('num_andar')

        fig_andar = px.bar(
            df_andar, 
            x='num_andar', 
            y='Custo_Mensal_R$', 
            color='Custo_Mensal_R$',
            color_continuous_scale='Reds',
            labels={'num_andar': 'Andar', 'Custo_Mensal_R$': 'Custo Estimado (R$)'},
            text_auto='.2s'
        )
        fig_andar.update_layout(xaxis_type='category') 
        st.plotly_chart(fig_andar, use_container_width=True)

        # VISUALIZAÇÃO POR SALA (SELETOR)
        st.divider()
        st.subheader("🚪 Detalhamento por Sala")
        
        # Pega a lista de salas únicas e ordenadas
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        
        # Seletor interativo
        sala_selecionada = st.selectbox("Selecione a Sala para ver detalhes:", lista_salas)
        
        if sala_selecionada:
            # Filtra o DataFrame original
            df_sala_detalhe = df_raw[df_raw['Id_sala'] == sala_selecionada]
            
            # Métricas da Sala
            custo_sala = df_sala_detalhe['Custo_Mensal_R$'].sum()
            potencia_sala = df_sala_detalhe['Potencia_Total_Item_W'].sum()
            qtd_equip = df_sala_detalhe['Quant'].sum()
            andar_sala = df_sala_detalhe['num_andar'].iloc[0] if not df_sala_detalhe.empty else "N/A"
            
            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            col_s1.metric("Custo Mensal da Sala", f"R$ {custo_sala:,.2f}")
            col_s2.metric("Potência Instalada", f"{potencia_sala:,.0f} W")
            col_s3.metric("Qtd. Equipamentos", f"{qtd_equip}")
            col_s4.metric("Localização", f"Andar {andar_sala}")
            
            # Tabela de Equipamentos da Sala
            st.markdown(f"**Equipamentos na Sala: {sala_selecionada}**")
            st.dataframe(
                df_sala_detalhe[['des_nome_equipamento', 'des_categoria', 'Quant', 'num_potencia', 'Custo_Mensal_R$']]
                .sort_values(by='Custo_Mensal_R$', ascending=False)
                .reset_index(drop=True),
                use_container_width=True
            )

    with tab4:
        st.subheader("💰 Viabilidade Econômica (ROI)")
        st.markdown("Estime o investimento (CAPEX) necessário para as substituições e calcule o tempo de retorno (Payback).")

        # 1. Inputs de Custo (Capex)
        with st.expander("🛠️ Configurar Custos de Investimento (Estimados)", expanded=True):
            col_inv1, col_inv2, col_inv3 = st.columns(3)
            
            # Iluminação
            custo_lampada = col_inv1.number_input("Custo Unit. Lâmpada LED (R$)", value=25.0, step=5.0)
            custo_sensor = col_inv1.number_input("Custo Unit. Sensor Presença (R$)", value=60.0, step=10.0)
            
            # Climatização
            custo_ac_novo = col_inv2.number_input("Custo Unit. Ar Inverter (R$)", value=3500.0, step=100.0)
            perc_troca_ac = col_inv2.slider("% do Parque de Ar a substituir", 0, 100, 40, help="Considerando apenas os aparelhos mais antigos")
            
            # Informática
            custo_pc_novo = col_inv3.number_input("Custo Unit. Mini PC (R$)", value=2800.0, step=100.0)
            perc_troca_pc = col_inv3.slider("% do Parque de PCs a substituir", 0, 100, 30, help="Foco em torres antigas")

        # 2. Quantidades (Baseado no Inventário)
        # Iluminação: Troca total assumida (baixo custo unitário, alto retorno)
        qtd_lampadas = int(df_raw[df_raw['Categoria_Macro'] == 'Iluminação']['Quant'].sum())
        qtd_sensores = int(qtd_lampadas / 10) # Estimativa: 1 sensor para cada 10 lâmpadas em áreas comuns
        
        # Climatização
        qtd_ac_total = int(df_raw[df_raw['Categoria_Macro'] == 'Climatização']['Quant'].sum())
        qtd_ac_troca = int(qtd_ac_total * (perc_troca_ac/100))
        
        # Informática
        qtd_pc_total = int(df_raw[df_raw['Categoria_Macro'] == 'Informática']['Quant'].sum())
        qtd_pc_troca = int(qtd_pc_total * (perc_troca_pc/100))

        # 3. Cálculo do Investimento Total (CAPEX)
        inv_iluminacao = (qtd_lampadas * custo_lampada) + (qtd_sensores * custo_sensor)
        inv_climatizacao = qtd_ac_troca * custo_ac_novo
        inv_informatica = qtd_pc_troca * custo_pc_novo
        inv_total = inv_iluminacao + inv_climatizacao + inv_informatica

        # 4. Cálculo da Economia Mensal Real (OPEX Reduzido)
        # Recalcula economia baseada estritamente nos sliders desta aba
        custo_atual_clima = df_dashboard[df_dashboard['Categoria_Macro'] == 'Climatização']['Custo_Mensal_R$'].sum()
        eco_mensal_clima = (custo_atual_clima * (perc_troca_ac/100)) * 0.50 # Assumindo 50% de ganho de eficiência na troca
        
        custo_atual_info = df_dashboard[df_dashboard['Categoria_Macro'] == 'Informática']['Custo_Mensal_R$'].sum()
        eco_mensal_info = (custo_atual_info * (perc_troca_pc/100)) * 0.40 # Assumindo 40% de ganho
        
        # Iluminação mantém a base total pois assumimos troca global
        eco_mensal_ilum = df_dashboard[df_dashboard['Categoria_Macro'] == 'Iluminação']['Economia_Estimada_R$'].sum()
        
        eco_mensal_total = eco_mensal_ilum + eco_mensal_clima + eco_mensal_info
        
        # 5. Payback
        payback_meses = inv_total / eco_mensal_total if eco_mensal_total > 0 else 0
        payback_anos = payback_meses / 12

        # 6. Display de Resultados
        st.markdown("### 📊 Resultado da Simulação")
        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("Investimento Total (CAPEX)", f"R$ {inv_total:,.2f}", delta="Custo Único", delta_color="inverse")
        col_res2.metric("Economia Mensal Gerada", f"R$ {eco_mensal_total:,.2f}", delta="Recorrente")
        col_res3.metric("Tempo de Retorno (Payback)", f"{payback_meses:.1f} meses", delta=f"{payback_anos:.1f} anos", delta_color="normal")

        # Detalhe do Investimento por Categoria
        chart_data = pd.DataFrame({
            'Categoria': ['Iluminação', 'Climatização', 'Informática'],
            'Investimento': [inv_iluminacao, inv_climatizacao, inv_informatica]
        })
        
        # Gráfico de Fluxo de Caixa (Break-even Point)
        st.subheader("📉 Curva de Payback (Ponto de Equilíbrio)")
        
        meses_projecao = int(payback_meses * 2.5) if payback_meses > 0 else 24
        if meses_projecao > 60: meses_projecao = 60 # Limitar gráfico a 5 anos
        
        fluxo = []
        saldo = -inv_total
        for m in range(meses_projecao + 1):
            fluxo.append({'Mês': m, 'Saldo Acumulado (R$)': saldo})
            saldo += eco_mensal_total
        
        df_fluxo = pd.DataFrame(fluxo)
        
        fig_fluxo = px.area(df_fluxo, x='Mês', y='Saldo Acumulado (R$)', markers=False,
                            color_discrete_sequence=['#00CC96'])
        
        # Adiciona linha zero (ponto de retorno)
        fig_fluxo.add_hline(y=0, line_dash="dash", line_color="white", annotation_text="Investimento Pago")
        fig_fluxo.update_layout(xaxis_title="Meses após implementação", yaxis_title="Fluxo de Caixa Acumulado (R$)")
        
        st.plotly_chart(fig_fluxo, use_container_width=True)
        
        st.info(f"""
        **Resumo do Plano:** Substituindo **{qtd_lampadas}** lâmpadas, **{qtd_ac_troca}** aparelhos de ar-condicionado e **{qtd_pc_troca}** computadores, 
        o projeto se paga em aproximadamente **{payback_meses:.0f} meses**.
        """)

    # --- 6. SIMULAÇÃO DE PICO ---
    st.divider()
    st.subheader("⚠️ Análise de Carga Instalada (Pico)")
    
    potencia_instalada_total_kw = df_raw['Potencia_Total_Item_W'].sum() / 1000
    custo_hora_full = potencia_instalada_total_kw * tarifa_kwh
    
    col_p1, col_p2 = st.columns(2)
    col_p1.metric("Potência Instalada Total", f"{potencia_instalada_total_kw:,.2f} kW")
    col_p2.metric("Custo por Hora (Carga Máxima)", f"R$ {custo_hora_full:,.2f} /h")
    
    st.caption("*O custo hora considera se todos os equipamentos fossem ligados simultaneamente.")

else:
    st.warning("Aguardando carregamento dos dados. Verifique se o link do GitHub está correto e público.")
