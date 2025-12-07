import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia - Reitoria", layout="wide", page_icon="⚡")

st.title("⚡ Eficiência Energética — Prédio da Reitoria (Baseline Out/2025)")
st.markdown("""
Painel ajustado conforme **Relatório Técnico de Diagnóstico Energético**.
Metodologia: **Bottom-Up** | Tarifa: **Grupo A4 Verde** | Janela: **07:00 às 18:30**.
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
# 1. CARREGAMENTO DOS DADOS
# ---------------------------------------------------
DATA_URL_INVENTARIO = "https://raw.githubusercontent.com/Web3economyst/UFRGS_Energy/refs/heads/main/Planilha%20Unificada(Equipamentos%20Consumo).csv"
DATA_URL_OCUPACAO = "https://github.com/Web3economyst/UFRGS_Energy/raw/main/Hor%C3%A1rios.xlsx"

@st.cache_data
def load_data():
    try:
        # INVENTÁRIO
        df_inv = pd.read_csv(DATA_URL_INVENTARIO, encoding='utf-8', on_bad_lines='skip')
        df_inv.columns = df_inv.columns.str.strip()

        df_inv['Quant'] = pd.to_numeric(df_inv['Quant'], errors='coerce').fillna(1)
        df_inv['num_potencia'] = pd.to_numeric(df_inv['num_potencia'], errors='coerce').fillna(0)

        # Tratamento de colunas de texto
        cols_txt = ['num_andar', 'Id_sala', 'Setor']
        for c in cols_txt:
            if c in df_inv.columns:
                df_inv[c] = df_inv[c].astype(str).str.strip().replace(['nan','NaN','', '0.0'], 'Não Identificado')
                if c == 'num_andar':
                    df_inv[c] = df_inv[c].str.replace(r'\.0$', '', regex=True)
            else:
                df_inv[c] = 'Não Identificado'

        # Conversão BTU -> Watts
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
            if nome_aba_dados is None: nome_aba_dados = xls.sheet_names[0]

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
# 2. SIDEBAR — PARÂMETROS E SAZONALIDADE
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Parâmetros (Baseline)")

        # TARIFAS CONFORME RELATÓRIO
        st.subheader("💰 Tarifas (Grupo A4 Verde)")
        st.caption("Valores estimados com impostos")
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            tarifa_ponta = st.number_input("Ponta (R$/kWh)", value=2.90, format="%.2f", step=0.1)
        with c_tar2:
            tarifa_fora_ponta = st.number_input("F. Ponta (R$/kWh)", value=0.70, format="%.2f", step=0.1)
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()
        st.subheader("🕒 Regime Operacional")
        
        # DEFINIÇÃO DE HORAS PADRÃO (07:00 as 18:30 = 11.5h)
        # O relatório cita invasão de 30 min no horário de ponta (18h-18h30)
        horas_expediente_padrao = 11.5
        dias_mes_padrao = 22

        dias_mes = st.number_input("Dias Úteis/Mês", value=dias_mes_padrao)
        
        with st.expander("Horas de Uso Diário (Ajuste Fino)"):
            st.caption("Padrão Relatório: 11.5h (07:00 - 18:30)")
            horas_ar = st.number_input("Climatização", value=horas_expediente_padrao, step=0.5)
            horas_luz = st.number_input("Iluminação", value=horas_expediente_padrao, step=0.5)
            horas_pc = st.number_input("Informática", value=horas_expediente_padrao, step=0.5)
            horas_eletro = st.number_input("Copa/Eletro", value=horas_expediente_padrao, step=0.5)
            horas_outros = st.number_input("Outros", value=horas_expediente_padrao, step=0.5)

        st.divider()
        st.subheader("⚠️ Salas 24h (Servidores/Geladeiras)")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas com regime 24h:", lista_salas)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS (AJUSTADOS AO RELATÓRIO)
    # ---------------------------------------------------

    def agrupar(cat):
        c = str(cat).upper().strip()
        if "CLIM" in c or "AR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c or "INFORM" in c or "NOBREAK" in c or "RACK" in c or "CPU" in c: return "Informática"
        if "ELETRO" in c or "DOMÉSTICO" in c or "COPA" in c or "COZINHA" in c or "GELADEIRA" in c or "FRIGOBAR" in c or "CHALEIRA" in c: return "Eletrodomésticos"
        if "ELEV" in c: return "Elevadores"
        if "BOMB" in c: return "Bombas"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar)

    # --- LÓGICA DE FATOR DE USO (DUTY CYCLE) DO RELATÓRIO ---
    # Ar = 0.60 | PC = 0.80 | Iluminação = 1.00 | 24h = 1.00
    fator_uso_dict = {
        'Climatização': 0.60,
        'Informática': 0.80,
        'Iluminação': 1.00,
        'Eletrodomésticos': 0.50, # Estimativa conservadora para cafeteiras/chaleiras que não ficam ligadas 11h direto
        'Elevadores': 0.20,
        'Outros': 0.50
    }
    
    # Ajuste fino para itens específicos citados no relatório que operam intermitentemente
    def get_fator_uso(row):
        nome = str(row['des_nome_equipamento']).upper()
        cat = row['Categoria_Macro']
        
        # Geladeiras/Servidores em salas normais ligam/desligam (termostato)
        if "GELADEIRA" in nome or "FRIGOBAR" in nome: return 0.50 
        if "BEBEDOURO" in nome: return 0.40
        
        # Se for sala 24h, assume regime contínuo, mas mantém ciclo termostato se aplicável
        return fator_uso_dict.get(cat, 0.50)

    # --- LÓGICA DE CUSTO (EXPEDIENTE vs PONTA) ---
    def calcular_custo_unitario_kwh(horas_uso_dia, is_24h):
        """
        Calcula o custo médio do kWh baseado no perfil de horário.
        Relatório: Expediente invade 30 min da ponta (18:00 as 18:30).
        """
        if is_24h:
            # 24h = 3h na ponta (18-21) + 21h fora ponta
            horas_ponta = 3
            horas_fora = 21
            total = 24
        else:
            # Expediente normal
            # Se trabalha até 18:30, tem 0.5h de ponta
            horas_ponta = 0.5 if horas_uso_dia >= 11.5 else 0
            horas_fora = max(0, horas_uso_dia - horas_ponta)
            total = horas_uso_dia if horas_uso_dia > 0 else 1

        custo_medio = ((horas_ponta * tarifa_ponta) + (horas_fora * tarifa_fora_ponta)) / total
        return custo_medio

    # Aplicação dos Cálculos
    def processar_energia(row):
        cat = row['Categoria_Macro']
        is_24h = str(row['Id_sala']) in salas_24h
        
        # 1. Definição de Horas e Dias
        if is_24h:
            h = 24
            d = 30 # Equipamento 24h roda 30 dias
        else:
            d = dias_mes
            if cat == "Climatização": h = horas_ar
            elif cat == "Iluminação": h = horas_luz
            elif cat == "Informática": h = horas_pc
            elif cat == "Eletrodomésticos": h = horas_eletro
            else: h = horas_outros

        # 2. Fator de Uso (Duty Cycle)
        fator = get_fator_uso(row)
        
        # Exceção para itens 24h reais (Servidores/Geladeiras em salas 24h)
        if is_24h and ("SERVIDOR" in str(row['des_nome_equipamento']).upper() or "RACK" in str(row['des_nome_equipamento']).upper()):
            fator = 1.0 # Servidor não para

        # 3. Consumo (kWh)
        # Formula: (W * Qtd * H * Dias * Fator) / 1000
        consumo_kwh = (row['Potencia_Total_Item_W'] * h * d * fator) / 1000
        
        # 4. Custo (R$)
        preco_medio = calcular_custo_unitario_kwh(h, is_24h)
        custo_rs = consumo_kwh * preco_medio

        return pd.Series([consumo_kwh, custo_rs, preco_medio])

    df_raw[['Consumo_Mensal_kWh', 'Custo_Consumo_R$', 'Tarifa_Media_Item']] = df_raw.apply(processar_energia, axis=1)

    # Demanda (Mantida lógica padrão, mas ajustada visualização)
    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw['Potencia_Instalada_kW'] * df_raw['Categoria_Macro'].map(fator_uso_dict).fillna(0.5)

    # Totais Globais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    
    # Tarifa média global para exibição (ponderada pelo custo total / consumo total)
    tarifa_media_global = custo_total_consumo / consumo_total_kwh if consumo_total_kwh > 0 else 0

    # ---------------------------------------------------
    # 4. TABS DE VISUALIZAÇÃO
    # ---------------------------------------------------
    tab1, tab2, tab_eff, tab3, tab4 = st.tabs([
        "📉 Dimensionamento (kW)",
        "⚡ Consumo (kWh)",
        "💡 Eficiência",
        "💰 Viabilidade / ROI",
        "🏫 Detalhe por Andar / Sala"
    ])

    # ---------------------------------------------------
    # TAB 1 — DIMENSIONAMENTO
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        k2.metric("Pico Estimado (Simultaneidade)", formatar_br(total_demanda_pico_kw, sufixo=" kW", decimais=1), help="Considerando Fatores de Uso do Relatório")
        k3.metric("Custo Fixo Demanda", formatar_br(custo_demanda_fixo, prefixo="R$ "))
        
        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            pico = 0 if pd.isna(pico) else pico
            k4.metric("Pico de Ocupação", f"{int(pico)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        c_gauge, c_info = st.columns([1, 1.3])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Utilização Estimada (kW)"},
                gauge={
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "#1f77b4"},
                    'threshold': {'value': total_demanda_pico_kw, 'line': {'color': "red", 'width': 4}},
                }
            ))
            fig_gauge.update_layout(separators=",.")
            st.plotly_chart(fig_gauge, use_container_width=True)

        with c_info:
            st.markdown("### Demanda por Categoria (Fator de Uso Aplicado)")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            # Mostra o fator médio aplicado
            dft['Fator Médio'] = dft['Demanda_Estimada_kW'] / dft['Potencia_Instalada_kW']
            
            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=1),
                    'Demanda_Estimada_kW': lambda x: formatar_br(x, decimais=1),
                    'Fator Médio': lambda x: formatar_br(x, decimais=2),
                }),
                use_container_width=True, hide_index=True
            )

    # ---------------------------------------------------
    # TAB 2 — CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("⚡ Consumo Mensal e Custos (Fatura Sombra)")
        st.caption(f"Custo calculado com mix de tarifas (0.5h na Ponta R$ {tarifa_ponta:.2f} + 11h Fora Ponta R$ {tarifa_fora_ponta:.2f})")

        fatura_total = custo_demanda_fixo + custo_total_consumo

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Consumo Total", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0))
        k2.metric("Custo Energia (Variável)", formatar_br(custo_total_consumo, prefixo="R$ "))
        k3.metric("Fatura Total Estimada", formatar_br(fatura_total, prefixo="R$ "))
        k4.metric("Tarifa Média Efetiva", formatar_br(tarifa_media_global, prefixo="R$ ", sufixo="/kWh"))

        st.divider()

        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            # Gráfico Consumo
            df_cons_cat = df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index()
            fig_bar = px.bar(
                df_cons_cat,
                x='Categoria_Macro', y='Consumo_Mensal_kWh',
                color='Categoria_Macro', 
                title="Consumo por Categoria (kWh)"
            )
            fig_bar.update_layout(separators=",.")
            fig_bar.update_traces(texttemplate='%{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with col_g2:
            # Gráfico Custo
            df_cust_cat = df_raw.groupby('Categoria_Macro')['Custo_Consumo_R$'].sum().reset_index()
            fig_pie = px.pie(
                df_cust_cat,
                values='Custo_Consumo_R$', names='Categoria_Macro',
                title="Distribuição do Custo (R$)"
            )
            fig_pie.update_layout(separators=",.")
            fig_pie.update_traces(textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)

    # ---------------------------------------------------
    # TAB 3 — EFICIÊNCIA
    # ---------------------------------------------------
    with tab_eff:
        st.subheader("💡 Eficiência Energética")

        eficiencia_params = {
            "Iluminação": 0.50, # LED
            "Climatização": 0.35, # Inverter
            "Informática": 0.20, # Gestão Energia
            "Eletrodomésticos": 0.15,
            "Elevadores": 0.05,
            "Bombas": 0.15,
            "Outros": 0.10
        }

        resumo = df_raw.groupby("Categoria_Macro")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        resumo["Economia_R$"] = resumo["Custo_Consumo_R$"] * resumo["Reducao_%"]

        economia_total_kwh = resumo["Economia_kWh"].sum()
        economia_total_rs = resumo["Economia_R$"].sum()

        c1, c2 = st.columns(2)
        c1.metric("Economia Estimada (kWh)", formatar_br(economia_total_kwh, sufixo=" kWh/mês", decimais=0))
        c2.metric("Economia Financeira (R$)", formatar_br(economia_total_rs, prefixo="R$ ", sufixo="/mês"))

        st.dataframe(
            resumo.sort_values("Economia_R$", ascending=False).style.format({
                "Consumo_Mensal_kWh": lambda x: formatar_br(x, decimais=0),
                "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ "),
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
        st.subheader("💰 Simulador de Viabilidade")

        col_l, col_r = st.columns([1, 2])

        with col_l:
            investimento = st.number_input("Orçamento (R$):", value=50000.0, step=5000.0)
            custo_led = st.number_input("Troca p/ LED (Unit.)", value=25.0)
            custo_ar = st.number_input("Ar Inverter (Unit.)", value=3500.0)

        with col_r:
            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()

            max_inv_luz = qtd_luz * custo_led
            inv_luz = min(investimento, max_inv_luz)
            sobra_1 = investimento - inv_luz
            luz_trocadas = int(inv_luz / custo_led)

            max_inv_ar = qtd_ar * custo_ar
            inv_ar = min(sobra_1, max_inv_ar)
            ar_trocados = int(inv_ar / custo_ar)

            c1, c2 = st.columns(2)
            c1.metric("Lâmpadas Substituídas", formatar_br(luz_trocadas, sufixo=" un.", decimais=0))
            c2.metric("Ar-cond. Substituídos", formatar_br(ar_trocados, sufixo=" un.", decimais=0))

        st.divider()

        # Calculo de economia usando a tarifa média efetiva
        eco_luz_val = luz_trocadas * (0.030 * horas_luz * dias_mes * tarifa_media_global * 0.50)
        eco_ar_val = ar_trocados * (1.4 * horas_ar * dias_mes * tarifa_media_global * 0.35)

        economia_total_roi = eco_luz_val + eco_ar_val
        payback = investimento / economia_total_roi if economia_total_roi > 0 else 999

        k1, k2 = st.columns(2)
        k1.metric("Economia Mensal Gerada", formatar_br(economia_total_roi, prefixo="R$ "))
        k2.metric("Payback Estimado", formatar_br(payback, sufixo=" meses", decimais=1))

    # ---------------------------------------------------
    # TAB 5 — DETALHES
    # ---------------------------------------------------
    with tab4:
        st.subheader("Análise Detalhada (Top Consumers)")

        col_a, col_s = st.columns(2)

        with col_a:
            st.markdown("### 🏢 Ranking por Unidade (Setor)")
            
            df_setor_all = df_raw.groupby("Setor")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_setor_all = df_setor_all.sort_values("Custo_Consumo_R$", ascending=False)
            
            st.dataframe(
                df_setor_all.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

        with col_s:
            st.markdown("### 🏬 Ranking por Andar")
            
            df_andar_all = df_raw.groupby("num_andar")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_andar_all = df_andar_all.sort_values("Custo_Consumo_R$", ascending=False)

            st.dataframe(
                df_andar_all.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )
        
        st.divider()
        st.markdown("### 🔍 Drill-down por Equipamento Específico")
        
        target_keywords = [
            "AR CONDICIONADO", "CHALEIRA", "CAFETEIRA", "MICROONDAS", "AQUECEDOR"
        ]
        
        def is_target(nome):
            return any(k in str(nome).upper() for k in target_keywords)
        
        df_target = df_raw[df_raw['des_nome_generico_equipamento'].apply(is_target)].copy()
        
        if not df_target.empty:
            df_target_g = df_target.groupby("des_nome_generico_equipamento")[["Quant", "Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_target_g = df_target_g.sort_values("Custo_Consumo_R$", ascending=False)
            
            st.dataframe(
                df_target_g.style.format({
                    "Quant": "{:.0f}",
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

else:
    st.warning("Carregando dados... Verifique a conexão com o GitHub.")
