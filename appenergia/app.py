import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Relatório Energético - Reitoria", layout="wide", page_icon="⚡")

st.title("⚡ Diagnóstico Energético (AS-IS) — Edifício Reitoria")
st.markdown("""
**Base de Cálculo:** Relatório Técnico Outubro/2025.  
Metodologia **Bottom-Up** (Inventário x Fator de Uso x Tarifas A4 Verde).
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

        # Tratamento de Strings
        for col in ['num_andar', 'Id_sala', 'Setor']:
            if col in df_inv.columns:
                df_inv[col] = df_inv[col].astype(str).str.strip().replace(['nan','NaN','', 'nan.0'], 'Não Identificado')
                df_inv[col] = df_inv[col].astype(str).str.replace(r'\.0$', '', regex=True)
            else:
                df_inv[col] = 'Não Identificado'

        # Conversão BTU -> Watts e Limpeza
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row['des_potencia']).upper()
            # Fórmula aproximada BTU -> W (divide por 3.41 ou aprox 3.0 conservador)
            return p * 0.293 if 'BTU' in u else p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']

        # OCUPAÇÃO (Mantida apenas para visualização de fluxo)
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba_dados = xls.sheet_names[0]
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                cols = [str(x).strip() for x in df_temp.columns]
                if 'DataHora' in cols and 'EntradaSaida' in cols:
                    nome_aba_dados = aba
                    break

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
# 2. SIDEBAR — PARÂMETROS DO RELATÓRIO
# ---------------------------------------------------
if not df_raw.empty:
    with st.sidebar:
        st.header("⚙️ Premissas (Baseline)")

        # TARIFAS (Atualizadas conforme relatório)
        st.subheader("💰 Tarifas A4 Verde (R$/kWh)")
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            tarifa_ponta = st.number_input("Ponta (18h-21h)", value=2.90, format="%.2f", help="Conforme relatório: R$ 2,90")
        with c_tar2:
            tarifa_fora_ponta = st.number_input("Fora Ponta", value=0.70, format="%.2f", help="Conforme relatório: R$ 0,70")
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()
        
        st.subheader("🕒 Janela Operacional")
        dias_mes = st.number_input("Dias Úteis / Mês", value=22, help="Padrão Relatório: 22 dias")
        
        st.info("**Expediente: 07:00 às 18:30**\n\nIsso impacta o cálculo pois invade 30min do horário de ponta.")

        # Slider apenas para visualização, pois o cálculo será fixo na lógica do relatório
        horas_expediente = 11.5 

        st.divider()
        st.subheader("⚠️ Equipamentos 24h")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Salas Servidor/Geladeiras:", lista_salas)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS (AJUSTADOS AO RELATÓRIO)
    # ---------------------------------------------------

    def classificar_macro(cat):
        c = str(cat).upper().strip()
        if any(x in c for x in ["AR COND", "CLIM", "SPLIT", "VENTILADOR", "AQUECEDOR"]): return "Climatização"
        if any(x in c for x in ["ILUM", "LÂMP", "REFLETOR"]): return "Iluminação"
        if any(x in c for x in ["COMP", "MONITOR", "INFORM", "CPU", "NOTEBOOK", "IMPRESSORA", "NOBREAK", "ESTABILIZADOR"]): return "Informática"
        if any(x in c for x in ["GELADEIRA", "FRIGOBAR", "MICRO", "CAFÉ", "CAFETEIRA", "CHALEIRA", "BEBEDOURO"]): return "Copa/Eletro"
        if "ELEV" in c: return "Elevadores"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(classificar_macro)

    # ---------------------------------------------------
    # LÓGICA CENTRAL DE CÁLCULO (Relatório Item 2.2)
    # ---------------------------------------------------
    def calcular_consumo_custo(row):
        cat = row['Categoria_Macro']
        equip = str(row['des_nome_generico_equipamento']).upper()
        
        # 1. Definir FATOR DE USO (Duty Cycle) conforme relatório
        fator_uso = 1.0 # Padrão (Iluminação e outros)
        
        if cat == "Climatização":
            fator_uso = 0.60 # Compressores ciclando
        elif cat == "Informática":
            fator_uso = 0.80 # Ociosidade
        elif cat == "Copa/Eletro":
            # Geladeiras são 24h mas compressor cicla (aprox 0.5 a 0.7, mas relatório trata cargas 24h como 1.0 ou específico)
            # Para simplificar conforme relatório que cita "Cargas 24h: 1.0", vamos manter 1.0 para geladeiras se for 24h
            if "GELADEIRA" in equip or "FRIGOBAR" in equip:
                fator_uso = 0.50 # Média física, mas ajustável
            else:
                fator_uso = 0.30 # Uso intermitente (cafeteira, microondas)
        
        # Ajuste específico do relatório para Chaleiras/Cafeteiras que somam muito
        if "CHALEIRA" in equip or "CAFETEIRA" in equip: 
             fator_uso = 0.40 # Uso alto estimado

        # 2. Definir HORAS e DIAS
        # Se for sala 24h ou equipamento 24h
        eh_24h = (str(row['Id_sala']) in salas_24h) or ("GELADEIRA" in equip) or ("FRIGOBAR" in equip) or ("SERVIDOR" in equip) or ("RACK" in equip)

        if eh_24h:
            dias_calc = 30
            # 24h totais divididas em Ponta (3h: 18-21) e Fora (21h)
            h_ponta = 3.0
            h_fora = 21.0
            # Se for geladeira, o fator de uso já ajusta o ciclo do motor
        else:
            dias_calc = dias_mes # 22 dias
            # Janela 07:00 as 18:30 (11.5h totais)
            # 18:00 as 18:30 = 0.5h na PONTA
            # 07:00 as 18:00 = 11.0h na FORA PONTA
            h_ponta = 0.5
            h_fora = 11.0
        
        # Potência em kW
        pot_kw = row['Potencia_Total_Item_W'] / 1000.0
        
        # Consumo kWh = kW * (H_ponta + H_fora) * Dias * Fator
        horas_totais_dia = h_ponta + h_fora
        consumo_mensal_kwh = pot_kw * horas_totais_dia * dias_calc * fator_uso
        
        # Custo R$ = (kW * Fator) * Dias * [ (H_ponta * Tarifa_P) + (H_fora * Tarifa_FP) ]
        custo_ponta = (pot_kw * fator_uso) * dias_calc * (h_ponta * tarifa_ponta)
        custo_fora  = (pot_kw * fator_uso) * dias_calc * (h_fora * tarifa_fora_ponta)
        
        custo_mensal_rs = custo_ponta + custo_fora
        
        return pd.Series([consumo_mensal_kwh, custo_mensal_rs, fator_uso])

    # Aplicar cálculos
    df_raw[['Consumo_Mensal_kWh', 'Custo_Consumo_R$', 'Fator_Utilizado']] = df_raw.apply(calcular_consumo_custo, axis=1)

    # Demanda Estimada (Pico)
    fatores_demanda_pico = {
        'Climatização': 0.70, 'Iluminação': 1.00, 'Informática': 0.70,
        'Copa/Eletro': 0.50, 'Elevadores': 0.30, 'Outros': 0.50
    }
    
    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda_pico.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Totais Globais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()
    
    # Custo Demanda (Fixo)
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    
    # Fatura Total Estimada
    fatura_total = custo_demanda_fixo + custo_total_consumo

    # ---------------------------------------------------
    # 4. DASHBOARD E VISUALIZAÇÃO
    # ---------------------------------------------------
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Visão Geral (Baseline)",
        "⚡ Detalhe Consumo",
        "🏢 Por Setor/Andar",
        "💰 Oportunidades (ROI)"
    ])

    # ---------------------------------------------------
    # TAB 1 — VISÃO GERAL
    # ---------------------------------------------------
    with tab1:
        st.subheader("Resultado da Simulação (Baseline AS-IS)")
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Custo Total Mensal", formatar_br(fatura_total, prefixo="R$ "))
        k2.metric("Consumo Energia", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0))
        k3.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        # Cálculo de Custo/Pessoa (aprox 192 servidores conforme relatório)
        k4.metric("Custo por Ocupante", formatar_br(fatura_total/192, prefixo="R$ "))

        st.divider()

        # Gráfico Gauge
        c_gauge, c_info = st.columns([1, 1.3])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Demanda de Pico Estimada (kW)"},
                gauge={'axis': {'range': [None, total_instalado_kw]}, 'bar': {'color': "#2ecc71"}}
            ))
            fig_gauge.update_layout(separators=",.")
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            # Fator de Carga
            fc = consumo_total_kwh / (total_demanda_pico_kw * 720)
            st.info(f"Fator de Carga do Prédio: **{formatar_br(fc, decimais=2)}** (Baixo = Ineficiência)")

        with c_info:
            st.markdown("### Top 5 Ofensores (Custo R$)")
            df_top = df_raw.groupby('des_nome_generico_equipamento')[['Quant', 'Custo_Consumo_R$']].sum().reset_index()
            df_top = df_top.sort_values('Custo_Consumo_R$', ascending=False).head(5)
            
            st.dataframe(df_top.style.format({
                'Quant': '{:.0f}',
                'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ ")
            }), use_container_width=True, hide_index=True)

    # ---------------------------------------------------
    # TAB 2 — DETALHE CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("Composição do Custo por Categoria")
        
        col_graf, col_tab = st.columns([1.5, 1])
        
        df_cat = df_raw.groupby('Categoria_Macro')[['Consumo_Mensal_kWh', 'Custo_Consumo_R$']].sum().reset_index()
        df_cat['% Custo'] = (df_cat['Custo_Consumo_R$'] / custo_total_consumo) * 100
        
        with col_graf:
            fig_pie = px.pie(df_cat, values='Custo_Consumo_R$', names='Categoria_Macro', 
                             title="Distribuição de Custos", hole=0.4)
            fig_pie.update_traces(textinfo='percent+label')
            fig_pie.update_layout(separators=",.")
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col_tab:
            st.dataframe(df_cat.sort_values('Custo_Consumo_R$', ascending=False).style.format({
                'Consumo_Mensal_kWh': lambda x: formatar_br(x, decimais=0),
                'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ "),
                '% Custo': '{:.1f}%'
            }), use_container_width=True, hide_index=True)
            
        st.divider()
        st.subheader("Lista Completa de Equipamentos")
        df_full = df_raw.groupby('des_nome_generico_equipamento')[['Quant', 'Potencia_Instalada_kW', 'Consumo_Mensal_kWh', 'Custo_Consumo_R$']].sum().reset_index()
        st.dataframe(
            df_full.sort_values('Custo_Consumo_R$', ascending=False).style.format({
                'Quant': '{:.0f}',
                'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=2),
                'Consumo_Mensal_kWh': lambda x: formatar_br(x, decimais=0),
                'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ ")
            }), use_container_width=True, hide_index=True
        )

    # ---------------------------------------------------
    # TAB 3 — SETORES E ANDARES
    # ---------------------------------------------------
    with tab3:
        st.subheader("📍 Onde está o consumo?")
        
        c_setor, c_andar = st.columns(2)
        
        with c_setor:
            st.markdown("### Top Setores (R$)")
            df_setor = df_raw.groupby('Setor')['Custo_Consumo_R$'].sum().reset_index().sort_values('Custo_Consumo_R$', ascending=False)
            st.dataframe(df_setor.head(10).style.format({'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ ")}), 
                         use_container_width=True, hide_index=True)
            
        with c_andar:
            st.markdown("### Verticalização (Andares)")
            df_andar = df_raw.groupby('num_andar')['Custo_Consumo_R$'].sum().reset_index().sort_values('Custo_Consumo_R$', ascending=False)
            
            fig_bar_andar = px.bar(df_andar, x='num_andar', y='Custo_Consumo_R$', text_auto='.2s', title="Custo por Andar")
            fig_bar_andar.update_layout(separators=",.")
            fig_bar_andar.update_traces(texttemplate='R$ %{y:,.0f}', textposition='outside')
            st.plotly_chart(fig_bar_andar, use_container_width=True)

    # ---------------------------------------------------
    # TAB 4 — OPORTUNIDADES (ROI)
    # ---------------------------------------------------
    with tab4:
        st.subheader("💰 Potencial de Economia (Estimativa)")
        
        # Parâmetros de Redução (Baseados em retrofit padrão)
        reducao_params = {
            "Iluminação": 0.60, # LED
            "Climatização": 0.35, # Inverter
            "Informática": 0.20, # Gestão de Energia
            "Copa/Eletro": 0.10, # Conscientização
            "Outros": 0.05
        }
        
        df_eco = df_raw.copy()
        df_eco['Reducao_Pct'] = df_eco['Categoria_Macro'].map(reducao_params).fillna(0)
        df_eco['Economia_R$'] = df_eco['Custo_Consumo_R$'] * df_eco['Reducao_Pct']
        
        eco_total = df_eco['Economia_R$'].sum()
        novo_custo = fatura_total - eco_total
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Fatura Atual", formatar_br(fatura_total, prefixo="R$ "))
        c2.metric("Fatura Projetada (Retrofit)", formatar_br(novo_custo, prefixo="R$ "))
        c3.metric("Economia Potencial Mensal", formatar_br(eco_total, prefixo="R$ "), delta="Oportunidade")
        
        st.divider()
        st.markdown("### Detalhe da Economia por Categoria")
        resumo_eco = df_eco.groupby('Categoria_Macro')[['Custo_Consumo_R$', 'Economia_R$']].sum().reset_index()
        resumo_eco['% Redução Aplicada'] = resumo_eco['Categoria_Macro'].map(reducao_params)
        
        st.dataframe(resumo_eco.sort_values('Economia_R$', ascending=False).style.format({
            'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ "),
            'Economia_R$': lambda x: formatar_br(x, prefixo="R$ "),
            '% Redução Aplicada': '{:.0%}'
        }), use_container_width=True, hide_index=True)

else:
    st.warning("Aguardando carregamento dos dados...")
