import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia (Diagnóstico)", layout="wide", page_icon="⚡")

st.title("⚡ Eficiência Energética — Prédio da Reitoria (Diagnóstico Robusto)")
st.markdown("""
Painel de **Diagnóstico Energético "As-Is"**.  
Baseado na modelagem *Bottom-Up*: **Carga Instalada + Perfil de Uso Real + Tarifação A4 (Sazonal Verde)**.
""")

# ---------------------------------------------------
# FUNÇÃO DE FORMATAÇÃO PT-BR
# ---------------------------------------------------
def formatar_br(valor, prefixo="", sufixo="", decimais=2):
    try:
        if pd.isna(valor):
            return "-"
        formato = f"{{:,.{decimais}f}}"
        texto = formato.format(valor)
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{prefixo}{texto}{sufixo}"
    except Exception:
        return str(valor)

# ---------------------------------------------------
# 1. CARREGAMENTO E TRATAMENTO DOS DADOS (Refinado)
# ---------------------------------------------------
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/refs/heads/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # --- INVENTÁRIO ---
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='utf-8', on_bad_lines='skip')
        df_inv.columns = df_inv.columns.str.strip()

        # Limpeza básica
        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)
        
        # Tratamento de textos
        cols_texto = ['num_andar', 'Id_sala', 'Setor', 'des_nome_generico_equipamento', 'des_categoria', 'des_potencia']
        for col in cols_texto:
            if col in df_inv.columns:
                df_inv[col] = df_inv[col].astype(str).str.strip().replace(['nan','NaN',''], 'Não Identificado')
            else:
                df_inv[col] = 'Não Identificado'

        df_inv['num_andar'] = df_inv['num_andar'].str.replace(r'\.0$', '', regex=True)

        # --- LÓGICA ROBUSTA DE POTÊNCIA (Do Relatório) ---
        def estimar_potencia_real(row):
            potencia = row['num_potencia']
            unidade = str(row['des_potencia']).upper()
            nome = str(row['des_nome_generico_equipamento']).lower()
            cat = str(row['des_categoria']).lower()

            # 1. Imputação de Valores Faltantes (Heurística de Mercado)
            if potencia <= 0:
                if 'ar condicionado' in nome: return 1400.0  # ~12000 BTU antigo
                if 'computador' in nome or 'cpu' in nome: return 200.0
                if 'monitor' in nome: return 30.0
                if 'chaleira' in nome: return 1200.0
                if 'cafeteira' in nome: return 800.0
                if 'geladeira' in nome: return 150.0
                if 'lâmpada' in nome or 'iluminação' in cat: return 32.0 # Tubular Fluorescente
                return 50.0 # Valor default seguro

            # 2. Conversão de Unidades
            if 'BTU' in unidade:
                # Watts Elétricos = (BTU * 0.293) / COP (Assumindo 3.0)
                return (potencia * 0.293) / 3.0
            if 'CV' in unidade or 'HP' in unidade:
                return potencia * 735.5
            if 'KW' in unidade:
                return potencia * 1000.0
            
            return float(potencia)

        df_inv['Potencia_Real_W'] = df_inv.apply(estimar_potencia_real, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']

        # --- OCUPAÇÃO ---
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba = xls.sheet_names[0] # Simplificação para pegar a primeira aba
            df_oc = pd.read_excel(xls, sheet_name=nome_aba)
            df_oc = df_oc.dropna(subset=['DataHora'])
            df_oc['DataHora'] = pd.to_datetime(df_oc['DataHora'], errors='coerce')
            df_oc = df_oc.sort_values('DataHora')

            # Cálculo simplificado de ocupação acumulada
            df_oc['Variacao'] = df_oc['EntradaSaida'].astype(str).str.upper().str[0].map({'E':1,'S':-1}).fillna(0)
            df_oc['Data_Dia'] = df_oc['DataHora'].dt.date
            
            def calc_ocupacao(g):
                g = g.sort_values('DataHora')
                g['Ocupacao_Acumulada'] = g['Variacao'].cumsum()
                # Ajuste para não começar negativo (assumindo que dia começa com 0)
                min_val = g['Ocupacao_Acumulada'].min()
                if min_val < 0: g['Ocupacao_Acumulada'] += abs(min_val)
                return g
            
            df_oc = df_oc.groupby('Data_Dia', group_keys=False).apply(calc_ocupacao)

        except Exception:
            df_oc = pd.DataFrame()

        return df_inv, df_oc

    except Exception as e:
        st.error(f"Erro crítico no carregamento: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_raw, df_ocupacao = load_data()

# ---------------------------------------------------
# 2. SIDEBAR — PARÂMETROS TÉCNICOS (Atualizados com Relatório)
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros do Diagnóstico")

        # Ajuste de Tarifas conforme Relatório (A4 Verde RS Estimado)
        st.subheader("💰 Tarifas (A4 Verde - R$/kWh)")
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            tarifa_ponta = st.number_input("Ponta (18h-21h)", value=2.90, format="%.2f", help="Horário caro.")
        with c_tar2:
            tarifa_fora_ponta = st.number_input("Fora Ponta", value=0.70, format="%.2f", help="Horário normal.")
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)
        dias_uteis = st.number_input("Dias Úteis / Mês", value=22, min_value=15, max_value=31)

        st.divider()
        st.subheader("🕒 Fatores de Uso (Duty Cycle)")
        st.info("Percentual de tempo que o equipamento opera na potência nominal quando ligado.")
        
        fator_uso_ar = st.slider("Ciclo Compressor Ar (%)", 30, 100, 60, help="Ar não fica 100% ligado no talo. O relatório sugeriu 60%.") / 100.0
        fator_uso_pc = st.slider("Uso Efetivo PC (%)", 30, 100, 80, help="Considera ociosidade.") / 100.0

        st.divider()
        st.subheader("🕒 Definição de Salas 24h")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas com operação ininterrupta:", lista_salas)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS (O CORAÇÃO DO MODELO)
    # ---------------------------------------------------

    def categorizar_macro(nome_cat):
        c = str(nome_cat).upper().strip()
        if "CLIM" in c or "AR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c or "INFORM" in c: return "Informática"
        if "ELETRO" in c or "DOMÉSTICO" in c or "COPA" in c or "COZINHA" in c: return "Eletrodomésticos"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(categorizar_macro)

    # --- LÓGICA DE CÁLCULO DE CONSUMO E CUSTO ---
    def calcular_cenario(row):
        cat = row['Categoria_Macro']
        nome = str(row['des_nome_generico_equipamento']).lower()
        potencia_kw = row['Potencia_Total_Item_W'] / 1000.0
        
        # 1. Definição de Horas e Fator de Uso
        is_24h = (str(row['Id_sala']) in salas_24h) or \
                 ('geladeira' in nome) or ('servidor' in nome) or ('rack' in nome) or ('nobreak' in nome)
        
        if is_24h:
            horas_dia = 24.0
            dias_mes = 30
            # Fator de uso específico para geladeira em 24h
            fator = 0.40 if 'geladeira' in nome else 1.0 
            
            # Tarifação 24h: Pega 3h de ponta cheia todos os dias úteis (aproximação)
            # Simplificação: 3h Ponta, 21h Fora Ponta
            horas_ponta_dia = 3.0
            horas_fora_dia = 21.0
        else:
            horas_dia = 11.5 # 07:00 as 18:30 (Baseado no relatório)
            dias_mes = dias_uteis
            
            if cat == "Climatização": fator = fator_uso_ar
            elif cat == "Informática": fator = fator_uso_pc
            elif cat == "Iluminação": fator = 1.0
            elif "chaleira" in nome or "cafeteira" in nome: 
                horas_dia = 1.0 # Uso esporádico
                fator = 1.0
            else: 
                fator = 0.5 # Outros genéricos
            
            # Tarifação Comercial (fecha 18:30): Pega 0.5h de Ponta (18:00-18:30)
            horas_ponta_dia = 0.5
            horas_fora_dia = max(0, horas_dia - horas_ponta_dia)

        # 2. Cálculo de Energia (kWh)
        consumo_mensal_kwh = potencia_kw * horas_dia * dias_mes * fator
        
        # 3. Cálculo de Custo (R$) - Split Ponta/Fora Ponta
        # Calcula a proporção de energia consumida na ponta vs fora
        proporcao_ponta = horas_ponta_dia / horas_dia
        kwh_ponta = consumo_mensal_kwh * proporcao_ponta
        kwh_fora = consumo_mensal_kwh * (1 - proporcao_ponta)
        
        custo_total = (kwh_ponta * tarifa_ponta) + (kwh_fora * tarifa_fora_ponta)

        return pd.Series([consumo_mensal_kwh, custo_total])

    df_raw[['Consumo_Mensal_kWh', 'Custo_Consumo_R$']] = df_raw.apply(calcular_cenario, axis=1)

    # Demanda (Fatores de Simultaneidade Ajustados)
    fatores_demanda = {
        'Climatização': 0.85, # Alta simultaneidade em dias quentes
        'Iluminação': 1.00,   # Tudo ligado
        'Informática': 0.70,  # Nem todos ligados ao mesmo tempo no pico maximo
        'Eletrodomésticos': 0.30, # Baixa simultaneidade (copa)
        'Outros': 0.50
    }

    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000.0
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Totais Globais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    
    # Tarifa média efetiva (para display)
    if consumo_total_kwh > 0:
        tarifa_media_efetiva = custo_total_consumo / consumo_total_kwh
    else:
        tarifa_media_efetiva = 0

    # ---------------------------------------------------
    # 4. TABS DE VISUALIZAÇÃO
    # ---------------------------------------------------
    tab1, tab2, tab_eff, tab3, tab4 = st.tabs([
        "📉 Dimensionamento (kW)",
        "⚡ Consumo (kWh e R$)",
        "💡 Potencial de Eficiência",
        "💰 Viabilidade / ROI",
        "🏫 Detalhe por Setor"
    ])

    # ---------------------------------------------------
    # TAB 1 — DIMENSIONAMENTO
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption("Baseado na carga instalada e fatores de simultaneidade do relatório.")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        k2.metric("Pico de Demanda Estimado", formatar_br(total_demanda_pico_kw, sufixo=" kW", decimais=1), delta_color="inverse")
        k3.metric("Custo Fixo Demanda", formatar_br(custo_demanda_fixo, prefixo="R$ "))
        
        ocupacao_pico = df_ocupacao['Ocupacao_Acumulada'].max() if not df_ocupacao.empty else 0
        k4.metric("Pico de Ocupação", f"{int(ocupacao_pico)} pessoas")

        st.divider()

        c_gauge, c_info = st.columns([1, 1.5])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Demanda Máxima Estimada (kW)"},
                gauge={
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "#1f77b4"},
                    'threshold': {'value': total_demanda_pico_kw, 'line': {'color': "red", 'width': 4}},
                }
            ))
            fig_gauge.update_layout(separators=",.")
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            st.info(f"O Fator de Carga calculado no relatório foi de **0.32**. Isso indica alta ociosidade fora dos horários de pico.")

        with c_info:
            st.markdown("### Composição da Demanda")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Custo Demanda (R$)'] = dft['Demanda_Estimada_kW'] * tarifa_kw_demanda

            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=1),
                    'Demanda_Estimada_kW': lambda x: formatar_br(x, decimais=1),
                    'Custo Demanda (R$)': lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

    # ---------------------------------------------------
    # TAB 2 — CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("⚡ Consumo Mensal e Custo Operacional")
        
        fatura_total = custo_demanda_fixo + custo_total_consumo
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Consumo Mensal", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0))
        c2.metric("Custo de Energia", formatar_br(custo_total_consumo, prefixo="R$ "))
        c3.metric("Fatura Estimada (Total)", formatar_br(fatura_total, prefixo="R$ "), help="Inclui demanda + consumo.")
        c4.metric("Tarifa Média Efetiva", formatar_br(tarifa_media_efetiva, prefixo="R$ ", sufixo="/kWh"), help="Preço médio ponderado pelo perfil de uso.")

        st.divider()

        col_graf1, col_graf2 = st.columns(2)
        
        with col_graf1:
            st.markdown("#### Consumo (kWh) por Categoria")
            df_cons_cat = df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index()
            fig_pie = px.pie(df_cons_cat, values='Consumo_Mensal_kWh', names='Categoria_Macro', hole=0.4)
            fig_pie.update_layout(separators=",.")
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_graf2:
            st.markdown("#### Impacto no Custo (R$) por Categoria")
            df_cust_cat = df_raw.groupby('Categoria_Macro')['Custo_Consumo_R$'].sum().reset_index()
            fig_bar = px.bar(df_cust_cat, x='Categoria_Macro', y='Custo_Consumo_R$', color='Categoria_Macro')
            fig_bar.update_layout(separators=",.", showlegend=False)
            fig_bar.update_traces(texttemplate='R$ %{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)

    # ---------------------------------------------------
    # TAB 3 — EFICIÊNCIA
    # ---------------------------------------------------
    with tab_eff:
        st.subheader("💡 Potencial de Eficiência Energética")
        st.markdown("Estimativa de economia baseada na substituição tecnológica e ajustes de horário (corte de ponta).")

        # Parâmetros de Redução Conservadores (Baseados em Retrofit)
        eficiencia_params = {
            "Iluminação": 0.50, # LED vs Fluorescente
            "Climatização": 0.30, # Inverter vs Antigo + Ajuste Setpoint
            "Informática": 0.20, # Gestão de Energia (Sleep)
            "Eletrodomésticos": 0.10,
            "Outros": 0.05
        }

        resumo = df_raw.groupby("Categoria_Macro")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params).fillna(0)
        
        # Economia Financeira é maior na Climatização pois impacta a PONTA
        def calc_econ_rs(row):
            econ_kwh = row['Consumo_Mensal_kWh'] * row['Reducao_%']
            # Se for climatização, o impacto financeiro é bonificado por evitar ponta
            fator_valor = 1.1 if row['Categoria_Macro'] == 'Climatização' else 1.0
            return (row['Custo_Consumo_R$'] * row['Reducao_%']) * fator_valor

        resumo["Economia_R$"] = resumo.apply(calc_econ_rs, axis=1)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]

        eco_total_rs = resumo["Economia_R$"].sum()
        eco_total_kwh = resumo["Economia_kWh"].sum()

        k1, k2 = st.columns(2)
        k1.metric("Economia Potencial Mensal", formatar_br(eco_total_rs, prefixo="R$ "))
        k2.metric("Redução de Consumo", formatar_br(eco_total_kwh, sufixo=" kWh"))

        st.dataframe(
            resumo[["Categoria_Macro", "Reducao_%", "Economia_kWh", "Economia_R$"]]
            .sort_values("Economia_R$", ascending=False)
            .style.format({
                "Reducao_%": "{:.0%}",
                "Economia_kWh": lambda x: formatar_br(x, decimais=0),
                "Economia_R$": lambda x: formatar_br(x, prefixo="R$ ")
            }),
            use_container_width=True, hide_index=True
        )

    # ---------------------------------------------------
    # TAB 4 — VIABILIDADE
    # ---------------------------------------------------
    with tab3:
        st.subheader("💰 Simulador de Viabilidade (ROI)")

        col_l, col_r = st.columns([1, 2])
        with col_l:
            investimento = st.number_input("Orçamento Disponível (R$)", value=100000.0, step=10000.0)
            
            st.markdown("#### Custos Médios de Retrofit")
            custo_led = st.number_input("Ponto LED (R$)", value=40.0)
            custo_ar = st.number_input("Ar Inverter (R$)", value=4000.0)
            custo_pc = st.number_input("Otimização TI (R$)", value=100.0, help="Licença sw ou sensor")

        with col_r:
            st.markdown("### Alocação Inteligente")
            # Quantitativos
            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()
            
            # 1. Prioridade: Trocar todas as lâmpadas (ROI rápido)
            custo_total_luz = qtd_luz * custo_led
            if investimento >= custo_total_luz:
                inv_luz = custo_total_luz
                luz_trocadas = qtd_luz
            else:
                inv_luz = investimento
                luz_trocadas = int(investimento / custo_led)
            
            sobra = investimento - inv_luz
            
            # 2. Prioridade: Ar Condicionado (Maior custo op)
            if sobra > 0:
                ar_possiveis = int(sobra / custo_ar)
                ar_trocados = min(ar_possiveis, qtd_ar)
                inv_ar = ar_trocados * custo_ar
            else:
                ar_trocados = 0
                inv_ar = 0

            # Economia Gerada (Usando dados reais calculados na Tab Anterior)
            # Economia unitária média
            econ_unit_luz = (resumo[resumo['Categoria_Macro']=='Iluminação']['Economia_R$'].sum() / qtd_luz) if qtd_luz > 0 else 0
            econ_unit_ar = (resumo[resumo['Categoria_Macro']=='Climatização']['Economia_R$'].sum() / qtd_ar) if qtd_ar > 0 else 0
            
            economia_projetada = (luz_trocadas * econ_unit_luz) + (ar_trocados * econ_unit_ar)
            payback = investimento / economia_projetada if economia_projetada > 0 else 999

            c1, c2, c3 = st.columns(3)
            c1.metric("Lâmpadas Substituídas", f"{int(luz_trocadas)}")
            c2.metric("Ares Trocados", f"{int(ar_trocados)}")
            c3.metric("Payback Simples", formatar_br(payback, sufixo=" meses", decimais=1))

            if payback < 24:
                st.success(f"✅ Projeto altamente viável! Retorno em {payback:.1f} meses.")
            else:
                st.warning(f"⚠️ Retorno longo ({payback:.1f} meses). Considere aumentar o orçamento para equipamentos de maior impacto.")

    # ---------------------------------------------------
    # TAB 5 — DETALHES
    # ---------------------------------------------------
    with tab4:
        st.subheader("Análise Detalhada por Setor e Andar")

        col_a, col_s = st.columns(2)

        with col_a:
            st.markdown("### 🏢 Top Setores (Custo)")
            df_setor = df_raw.groupby('Setor')[['Custo_Consumo_R$', 'Consumo_Mensal_kWh']].sum().reset_index()
            df_setor = df_setor.sort_values('Custo_Consumo_R$', ascending=False).head(10)
            
            st.dataframe(
                df_setor.style.format({
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ "),
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0)
                }),
                use_container_width=True, hide_index=True
            )

        with col_s:
            st.markdown("### 🏬 Custo por Andar")
            df_andar = df_raw.groupby('num_andar')[['Custo_Consumo_R$']].sum().reset_index()
            # Tentar ordenar numericamente se possível
            try:
                df_andar['num'] = pd.to_numeric(df_andar['num_andar'], errors='coerce')
                df_andar = df_andar.sort_values('num')
            except:
                df_andar = df_andar.sort_values('num_andar')

            st.dataframe(
                df_andar[['num_andar', 'Custo_Consumo_R$']].style.format({
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

        st.divider()
        st.markdown("### 🔎 Drill-down: Equipamentos por Sala")
        sala_sel = st.selectbox("Selecione a Sala:", sorted(df_raw['Id_sala'].unique()))
        
        df_sala = df_raw[df_raw['Id_sala'] == sala_sel].copy()
        st.caption(f"Equipamentos na sala **{sala_sel}**")
        
        st.dataframe(
            df_sala[['des_nome_equipamento', 'Quant', 'Potencia_Real_W', 'Consumo_Mensal_kWh', 'Custo_Consumo_R$']]
            .sort_values('Custo_Consumo_R$', ascending=False)
            .style.format({
                'Potencia_Real_W': "{:.0f} W",
                'Consumo_Mensal_kWh': "{:.1f}",
                'Custo_Consumo_R$': "R$ {:.2f}"
            }),
            use_container_width=True
        )

else:
    st.info("Aguardando carregamento dos dados...")
