# dashboard_energia_revisado.py
# Versão revisada conforme RELATÓRIO AS-IS (Outubro 2025)
# Mantive estrutura original do dashboard e gráficos.
# Ajustes principais:
# - Separação kWh ponta / fora-ponta
# - Fatores de uso por tipologia (Ar 0.60, PC 0.80, Iluminação 1.00, cargas 24h 1.00)
# - Janela de expediente: 07:00-18:30 (11,5 h; 11h fora-ponta + 0.5h ponta)
# - Dias úteis padrão 22 (configurável)
# - Tarifas padrão: ponta 2.90 R$/kWh, fora-ponta 0.70 R$/kWh
# - Mantive demais calculos/visuais iguais ao original

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ---------------------------------------------------
# CONFIGURAÇÃO INICIAL
# ---------------------------------------------------
st.set_page_config(page_title="Dashboard de Energia", layout="wide", page_icon="⚡")

st.title("⚡ Eficiência Energética — Prédio da Reitoria")
st.markdown("""
Painel completo para **dimensionamento de demanda**, **consumo**, 
**análise de ocupação**, **eficiência** e **viabilidade econômica**.
""")

# ---------------------------------------------------
# FUNÇÃO DE FORMATAÇÃO PT-BR
# ---------------------------------------------------
def formatar_br(valor, prefixo="", sufixo="", decimais=2):
    """
    Formata números float para string no padrão brasileiro:
    1.234,56 (milhar com ponto, decimal com vírgula)
    """
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

        if 'num_andar' in df_inv.columns:
            df_inv['num_andar'] = df_inv['num_andar'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['num_andar'] = 'Não Identificado'

        if 'Id_sala' in df_inv.columns:
            df_inv['Id_sala'] = df_inv['Id_sala'].astype(str).replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['Id_sala'] = 'Não Identificado'
        
        if 'Setor' in df_inv.columns:
            df_inv['Setor'] = df_inv['Setor'].astype(str).str.strip().replace(['nan','NaN',''], 'Não Identificado')
        else:
            df_inv['Setor'] = 'Não Identificado'

        # Conversão BTU -> Watts (conservadora, mantém comportamento anterior)
        def converter_watts(row):
            p = row['num_potencia']
            u = str(row.get('des_potencia','')).upper()
            # Mantive a lógica original de tentativa de conversão BTU se aparecer
            try:
                if 'BTU' in u:
                    return p * 0.293 / 3.0
            except Exception:
                pass
            return p

        df_inv['Potencia_Real_W'] = df_inv.apply(converter_watts, axis=1)
        # Potencia_Total_Item_W contém já a multiplicação pela Quantidade (seguindo seu original)
        df_inv['Potencia_Total_Item_W'] = df_inv['Potencia_Real_W'] * df_inv['Quant']

        # OCUPAÇÃO (tenta ler a planilha de horários)
        try:
            xls = pd.ExcelFile(DATA_URL_OCUPACAO)
            nome_aba_dados = None
            for aba in xls.sheet_names:
                df_temp = pd.read_excel(xls, sheet_name=aba, nrows=5)
                cols = [str(x).strip() for x in df_temp.columns]
                if 'DataHora' in cols and 'EntradaSaida' in cols:
                    nome_aba_dados = aba
                    break
            if nome_aba_dados is None:
                nome_aba_dados = xls.sheet_names[0]

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
        st.header("⚙️ Parâmetros do Modelo")

        st.subheader("🌦️ Estação / Sazonalidade (mantido apenas visualmente)")
        periodo = st.radio("Selecione:", ["Verão (Alto Consumo)", "Inverno/Ameno (Baixo Consumo)"])

        # As tarifas padrão são fixas para aderir ao relatório AS-IS
        default_ponta = 2.90
        default_fora = 0.70

        # TARIFAS
        st.subheader("💰 Tarifas (R$/kWh)")
        c_tar1, c_tar2 = st.columns(2)
        with c_tar1:
            tarifa_ponta = st.number_input("Ponta", value=default_ponta, format="%.2f", help="Tarifa Ponta (R$/kWh)")
        with c_tar2:
            tarifa_fora_ponta = st.number_input("Fora Ponta", value=default_fora, format="%.2f", help="Tarifa Fora Ponta (R$/kWh)")
        
        tarifa_kw_demanda = st.number_input("Tarifa Demanda (R$/kW)", value=40.0)

        st.divider()
        st.subheader("🕒 Salas 24h")
        lista_salas = sorted(df_raw['Id_sala'].unique().astype(str))
        salas_24h = st.multiselect("Escolha:", lista_salas)

        with st.expander("Horas de Uso por Categoria (apenas para simulações, relatório usa 11.5h)"):
            horas_ar = st.slider("Ar Condicionado (h/dia)", 0, 24, 11)
            horas_luz = st.slider("Iluminação (h/dia)", 0, 24, 11)
            horas_pc = st.slider("Informática (h/dia)", 0, 24, 11)
            horas_eletro = st.slider("Eletrodomésticos (h/dia)", 0, 24, 5)
            horas_outros = st.slider("Outros (h/dia)", 0, 24, 6)
            dias_mes = st.number_input("Dias no mês (usar 22 para relatório)", value=22, min_value=1)

    # ---------------------------------------------------
    # 3. CÁLCULOS TÉCNICOS
    # ---------------------------------------------------

    def agrupar(cat):
        c = str(cat).upper().strip()
        if "CLIM" in c or "AR" in c: return "Climatização"
        if "ILUM" in c or "LÂMP" in c or "LAMP" in c: return "Iluminação"
        if "COMP" in c or "MONIT" in c or "INFORM" in c: return "Informática"
        if "ELETRO" in c or "DOMÉSTICO" in c or "COPA" in c or "COZINHA" in c: return "Eletrodomésticos"
        if "ELEV" in c: return "Elevadores"
        if "BOMB" in c: return "Bombas"
        return "Outros"

    df_raw['Categoria_Macro'] = df_raw['des_categoria'].apply(agrupar)

    # ----- parâmetros fixos do relatório -----
    HORAS_PONTA_PADRAO = 0.5          # 18:00 - 18:30
    HORAS_FORA_PONTA_PADRAO = 11.0    # 07:00 - 18:00
    HORAS_EXPEDIENTE_TOTAL = HORAS_FORA_PONTA_PADRAO + HORAS_PONTA_PADRAO  # 11.5
    DIAS_UTEIS_PADRAO = 22

    # Fatores de uso oficiais do relatório
    fatores_uso_oficiais = {
        'Climatização': 0.60,
        'Informática': 0.80,
        'Iluminação': 1.00,
        # cargas 24h ou equipamentos que devem operar 24h (servidores, geladeiras)
        # serão tratados dinamicamente
    }

    # Consumo: agora separa kWh_fora e kWh_ponta por equipamento
    def consumo(row):
        cat = row['Categoria_Macro']
        # Potência total já contém Quant (seguindo seu dataframe original)
        pot_w = row['Potencia_Total_Item_W']

        # Detecta se sala é 24h
        if str(row['Id_sala']) in salas_24h:
            # equipamento em sala 24h -> roda 24h por dia, todo dia do mês
            horas_fora = 24.0
            horas_ponta = 0.0
            dias = 30  # usar 30 dias para equipamentos 24h (comportamento original)
        else:
            horas_fora = HORAS_FORA_PONTA_PADRAO
            horas_ponta = HORAS_PONTA_PADRAO
            dias = dias_mes if 'dias_mes' in locals() else DIAS_UTEIS_PADRAO

        # fator de uso por categoria
        if cat == "Climatização":
            fator = fatores_uso_oficiais.get('Climatização', 0.6)
        elif cat == "Informática":
            fator = fatores_uso_oficiais.get('Informática', 0.8)
        elif cat == "Iluminação":
            fator = fatores_uso_oficiais.get('Iluminação', 1.0)
        else:
            # Por padrão, cargas que não se enquadram recebem fator 1.0 para aderir ao relatório
            # (o relatório trata muitos eletros como uso efetivo; se quiser reduzir, ajustar aqui)
            fator = 1.0

        # Consumos (kWh)
        kwh_fora = (pot_w * horas_fora * dias * fator) / 1000.0
        kwh_ponta = (pot_w * horas_ponta * dias * fator) / 1000.0

        # Salva para uso posterior
        row_result = pd.Series({
            'Consumo_Mensal_kWh': kwh_fora + kwh_ponta,
            'kWh_fora': kwh_fora,
            'kWh_ponta': kwh_ponta
        })
        return row_result

    # Aplicar linha a linha e juntar os resultados
    consumo_df = df_raw.apply(consumo, axis=1)
    df_raw['Consumo_Mensal_kWh'] = consumo_df['Consumo_Mensal_kWh']
    df_raw['kWh_fora'] = consumo_df['kWh_fora']
    df_raw['kWh_ponta'] = consumo_df['kWh_ponta']

    # Cálculo do custo variável usando tarifas de ponta e fora-ponta separadamente
    df_raw['Custo_Consumo_R$'] = df_raw['kWh_fora'] * tarifa_fora_ponta + df_raw['kWh_ponta'] * tarifa_ponta

    # Demanda (kW) - mantém lógica original mas ajusta nomenclatura
    fatores_demanda = {
        'Climatização': 0.85, 'Iluminação': 1.00, 'Informática': 0.70,
        'Eletrodomésticos': 0.50, 'Elevadores': 0.30, 'Bombas': 0.70, 'Outros': 0.50
    }

    df_raw['Potencia_Instalada_kW'] = df_raw['Potencia_Total_Item_W'] / 1000.0
    df_raw['Demanda_Estimada_kW'] = df_raw.apply(
        lambda x: x['Potencia_Instalada_kW'] * fatores_demanda.get(x['Categoria_Macro'], 0.5),
        axis=1
    )

    # Totais
    total_instalado_kw = df_raw['Potencia_Instalada_kW'].sum()
    total_demanda_pico_kw = df_raw['Demanda_Estimada_kW'].sum()
    consumo_total_kwh = df_raw['Consumo_Mensal_kWh'].sum()

    # Custo demanda fixo
    custo_demanda_fixo = total_demanda_pico_kw * tarifa_kw_demanda
    custo_total_consumo = df_raw['Custo_Consumo_R$'].sum()

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
    # TAB 1 — DIMENSIONAMENTO (BLOCO 1)
    # ---------------------------------------------------
    with tab1:
        st.subheader("📉 Dimensionamento de Demanda (kW)")
        st.caption(f"Estação atual: **{periodo}** — parâmetros do relatório: expediente 07:00–18:30 ({HORAS_EXPEDIENTE_TOTAL} h/dia), {dias_mes} dias/mês")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Potência Instalada", formatar_br(total_instalado_kw, sufixo=" kW", decimais=1))
        k2.metric("Pico Estimado (Demanda)", formatar_br(total_demanda_pico_kw, sufixo=" kW", decimais=1))
        k3.metric("Custo Fixo Demanda", formatar_br(custo_demanda_fixo, prefixo="R$ "))

        if not df_ocupacao.empty:
            pico = df_ocupacao['Ocupacao_Acumulada'].max()
            pico = 0 if pd.isna(pico) else pico
            k4.metric("Pico de Ocupação", f"{int(pico)} pessoas")
        else:
            k4.metric("Pico de Ocupação", "N/A")

        st.divider()

        if not df_ocupacao.empty:
            st.markdown("### 👥 Ocupação — Fluxo ao longo do tempo")
            fig_oc = px.line(df_ocupacao, x="DataHora", y="Ocupacao_Acumulada",
                             title="Fluxo de Pessoas (Acumulado Diário)")
            fig_oc.update_layout(separators=",.")
            st.plotly_chart(fig_oc, use_container_width=True)
            st.divider()

        c_gauge, c_info = st.columns([1, 1.3])
        with c_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_demanda_pico_kw,
                title={'text': "Utilização da Infraestrutura (kW)"},
                gauge={
                    'axis': {'range': [None, total_instalado_kw]},
                    'bar': {'color': "#1f77b4"},
                    'threshold': {'value': total_demanda_pico_kw, 'line': {'color': "red", 'width': 4}},
                }
            ))
            fig_gauge.update_layout(separators=",.")
            st.plotly_chart(fig_gauge, use_container_width=True)

            # Potência média real: consumo dividido por horas efetivas no mês
            # usamos dias_mes * 24 para representar o mês escolhido (normalmente 22 dias úteis no relatório, mas para média usamos o valor configurado)
            total_horas_mes = dias_mes * 24
            potencia_media_kw = consumo_total_kwh / total_horas_mes if total_horas_mes > 0 else 0
            kVA = total_demanda_pico_kw / 0.92 if total_demanda_pico_kw != 0 else 0
            st.info(f"⚙️ Transformador recomendado: **{formatar_br(kVA, decimais=0)} kVA** (FP = 0.92)")

        with c_info:
            st.markdown("### Tabela de Demanda por Categoria")
            dft = df_raw.groupby('Categoria_Macro')[['Potencia_Instalada_kW', 'Demanda_Estimada_kW']].sum().reset_index()
            dft['Fator'] = dft['Categoria_Macro'].map(fatores_demanda)
            dft['Custo Demanda (R$)'] = dft['Demanda_Estimada_kW'] * tarifa_kw_demanda

            st.dataframe(
                dft.sort_values('Demanda_Estimada_kW', ascending=False).style.format({
                    'Potencia_Instalada_kW': lambda x: formatar_br(x, decimais=1),
                    'Demanda_Estimada_kW': lambda x: formatar_br(x, decimais=1),
                    'Fator': lambda x: formatar_br(x, decimais=2),
                    'Custo Demanda (R$)': lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

        st.divider()

        st.markdown("### 🔍 Consumo Real (kWh) vs Capacidade (kW)")

        p1, p2, p3 = st.columns(3)
        p1.metric("Potência Média Real", formatar_br(potencia_media_kw, sufixo=" kW", decimais=1))
        uso_vs_pico_pct = (potencia_media_kw/total_demanda_pico_kw)*100 if total_demanda_pico_kw else 0
        uso_vs_instalado_pct = (potencia_media_kw/total_instalado_kw)*100 if total_instalado_kw else 0
        p2.metric("Uso vs Pico", formatar_br(uso_vs_pico_pct, sufixo="%"))
        p3.metric("Uso vs Instalada", formatar_br(uso_vs_instalado_pct, sufixo="%"))

        if potencia_media_kw < 0.7 * total_demanda_pico_kw:
            st.success("Uso real **bem abaixo do pico**.")
        elif potencia_media_kw < total_demanda_pico_kw:
            st.info("Uso **dentro da capacidade**, mas próximo do limite.")
        else:
            st.warning("⚠️ Uso real **acima do pico** — revise a demanda.")

    # ---------------------------------------------------
    # TAB 2 — CONSUMO
    # ---------------------------------------------------
    with tab2:
        st.subheader("⚡ Consumo Mensal (kWh)")

        fatura_total = custo_demanda_fixo + custo_total_consumo

        k1, k2, k3 = st.columns(3)
        k1.metric("Consumo Total", formatar_br(consumo_total_kwh, sufixo=" kWh", decimais=0))
        k2.metric("Custo Variável", formatar_br(custo_total_consumo, prefixo="R$ "))
        k3.metric("Conta Total Estimada", formatar_br(fatura_total, prefixo="R$ "))

        st.divider()

        # Gráfico Consumo por Categoria
        df_cons_cat = df_raw.groupby('Categoria_Macro')['Consumo_Mensal_kWh'].sum().reset_index()
        fig_bar = px.bar(
            df_cons_cat,
            x='Categoria_Macro', y='Consumo_Mensal_kWh',
            color='Categoria_Macro',
            title="Consumo por Categoria"
        )
        fig_bar.update_layout(separators=",.")
        fig_bar.update_traces(texttemplate='%{y:,.0f} kWh', textposition='outside')
        st.plotly_chart(fig_bar, use_container_width=True)

        # Tabela detalhada por categoria com custos ponta/fora
        df_cat_det = df_raw.groupby('Categoria_Macro').agg({
            'Consumo_Mensal_kWh':'sum',
            'kWh_fora':'sum',
            'kWh_ponta':'sum',
            'Custo_Consumo_R$':'sum'
        }).reset_index()
        st.dataframe(
            df_cat_det.sort_values('Custo_Consumo_R$', ascending=False).style.format({
                'Consumo_Mensal_kWh': lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                'kWh_fora': lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                'kWh_ponta': lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                'Custo_Consumo_R$': lambda x: formatar_br(x, prefixo="R$ ")
            }), use_container_width=True, hide_index=True
        )

    # ---------------------------------------------------
    # TAB 3 — 💡 EFICIÊNCIA
    # ---------------------------------------------------
    with tab_eff:
        st.subheader("💡 Eficiência Energética — Potencial de Redução (%) e Economia")

        st.markdown("""
        Abaixo você encontra um diagnóstico detalhado de **onde estão os maiores desperdícios**,  
        quanto pode ser economizado **por categoria**, e qual seria a **economia total mensal**.
        """)

        eficiencia_params = {
            "Iluminação": 0.60, "Climatização": 0.35, "Informática": 0.40,
            "Eletrodomésticos": 0.20, "Elevadores": 0.05, "Bombas": 0.15, "Outros": 0.10
        }

        resumo = df_raw.groupby("Categoria_Macro")["Consumo_Mensal_kWh"].sum().reset_index()
        resumo["Reducao_%"] = resumo["Categoria_Macro"].map(eficiencia_params).fillna(0.10)
        resumo["Economia_kWh"] = resumo["Consumo_Mensal_kWh"] * resumo["Reducao_%"]
        # Para estimativa de economia monetária usa-se tarifas separadas (aproximação: assume mix com mesma proporção)
        # A fórmula usada aqui multiplica pela tarifa média ponderada conforme consumo global
        tarifa_media_calculada = (tarifa_ponta * 0.5) + (tarifa_fora_ponta * 0.5)
        resumo["Economia_R$"] = resumo["Economia_kWh"] * tarifa_media_calculada

        economia_total_kwh = resumo["Economia_kWh"].sum()
        economia_total_rs = resumo["Economia_R$"].sum()

        c1, c2 = st.columns(2)
        c1.metric("Economia Máxima em Energia", formatar_br(economia_total_kwh, sufixo=" kWh/mês", decimais=0))
        c2.metric("Economia Máxima em Reais", formatar_br(economia_total_rs, prefixo="R$ ", sufixo="/mês"))

        st.divider()

        st.markdown("###  Economia por Categoria")
        st.dataframe(
            resumo.sort_values("Economia_R$", ascending=False).style.format({
                "Consumo_Mensal_kWh": lambda x: formatar_br(x, decimais=0),
                "Reducao_%": "{:.0%}",
                "Economia_kWh": lambda x: formatar_br(x, decimais=0),
                "Economia_R$": lambda x: formatar_br(x, prefixo="R$ ")
            }),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        col_b, col_p = st.columns([1.6, 1])
        with col_b:
            fig_econ = px.bar(
                resumo,
                x="Categoria_Macro",
                y="Economia_R$",
                title="Economia Potencial por Categoria (R$)",
                color="Categoria_Macro"
            )
            fig_econ.update_layout(separators=",.")
            fig_econ.update_traces(texttemplate='R$ %{y:,.2f}', textposition='outside')
            st.plotly_chart(fig_econ, use_container_width=True)

        with col_p:
            fig_pie_e = px.pie(
                resumo,
                values="Economia_R$",
                names="Categoria_Macro",
                hole=0.4,
                title="Distribuição da Economia"
            )
            fig_pie_e.update_layout(separators=",.")
            fig_pie_e.update_traces(textinfo='percent+label')
            st.plotly_chart(fig_pie_e, use_container_width=True)

    # ---------------------------------------------------
    # TAB 4 — VIABILIDADE / ROI
    # ---------------------------------------------------
    with tab3:
        st.subheader("💰 Simulador de Viabilidade — ROI do Projeto")

        col_l, col_r = st.columns([1, 2])

        with col_l:
            st.markdown("### Parâmetros do Projeto")
            investimento = st.number_input(
                "Orçamento disponível (R$):",
                value=50000.0,
                step=5000.0
            )

            st.markdown("#### 🔧 Custos unitários de modernização")
            custo_led = st.number_input("Troca p/ LED (R$)", value=25.0)
            custo_ar = st.number_input("Ar Inverter (R$)", value=3500.0)
            custo_pc = st.number_input("Mini PC (R$)", value=2800.0)

            st.info("""
            📌 **Ordem de prioridade automática:** 1) Iluminação → 2) Climatização → 3) Informática  
            """)

        with col_r:
            st.markdown("### Distribuição automática da verba")

            qtd_luz = df_raw[df_raw["Categoria_Macro"] == "Iluminação"]["Quant"].sum()
            qtd_ar = df_raw[df_raw["Categoria_Macro"] == "Climatização"]["Quant"].sum()
            qtd_pc = df_raw[df_raw["Categoria_Macro"] == "Informática"]["Quant"].sum()

            max_inv_luz = qtd_luz * custo_led
            inv_luz = min(investimento, max_inv_luz)
            sobra_1 = investimento - inv_luz
            luz_trocadas = int(inv_luz / custo_led) if custo_led > 0 else 0

            max_inv_ar = qtd_ar * custo_ar
            inv_ar = min(sobra_1, max_inv_ar)
            sobra_2 = sobra_1 - inv_ar
            ar_trocados = int(inv_ar / custo_ar) if custo_ar > 0 else 0

            max_inv_pc = qtd_pc * custo_pc
            inv_pc = min(sobra_2, max_inv_pc)
            pc_trocados = int(inv_pc / custo_pc) if custo_pc > 0 else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Lâmpadas instaladas", formatar_br(luz_trocadas, sufixo=" un.", decimais=0))
            c2.metric("Ar-condicionados novos", formatar_br(ar_trocados, sufixo=" un.", decimais=0))
            c3.metric("Mini PCs adquiridos", formatar_br(pc_trocados, sufixo=" un.", decimais=0))

        st.divider()

        st.markdown("### 📉 Economia Mensal Estimada")
        st.caption("Estimativa simplificada (tarifa média usada para compressão de cálculo financeiro)")

        # Fórmulas aproximadas para economia por tipo de ação (mantive a lógica original)
        eco_luz = luz_trocadas * (0.030 * horas_luz * dias_mes * tarifa_media_calculada * 0.60)
        eco_ar = ar_trocados * (1.4 * horas_ar * dias_mes * tarifa_media_calculada * 0.35)
        eco_pc = pc_trocados * (0.115 * horas_pc * dias_mes * tarifa_media_calculada)

        economia_total = eco_luz + eco_ar + eco_pc
        payback = investimento / economia_total if economia_total > 0 else 999

        k1, k2 = st.columns(2)
        k1.metric("Economia Mensal", formatar_br(economia_total, prefixo="R$ "))
        k2.metric("Payback Estimado", formatar_br(payback, sufixo=" meses", decimais=1))

        if payback < 12:
            st.success("🔋 Excelente viabilidade — retorno inferior a 1 ano.")
        elif payback < 36:
            st.info("Boa viabilidade — retorno moderado.")
        else:
            st.warning("Retorno longo — investimento pouco atrativo.")

    # ---------------------------------------------------
    # TAB 5 — DETALHES ANDAR / SALA
    # ---------------------------------------------------
    with tab4:
        st.subheader("Análise detalhada")

        col_a, col_s = st.columns(2)

        with col_a:
            st.markdown("### 🏢 Consumo por Setor")
            qtd_por_setor = df_raw.groupby('Setor')['Quant'].sum()
            media_aparelhos_setor = qtd_por_setor.mean() if len(qtd_por_setor)>0 else 0
            st.metric("Média de Aparelhos por Unidade Adm.", formatar_br(media_aparelhos_setor, sufixo=" un.", decimais=0))

            st.markdown("#### 🔍 Detalhar Setor")
            lista_setores = sorted(df_raw['Setor'].unique())
            setor_sel = st.selectbox("Selecione a Unidade Administrativa:", lista_setores, key="sel_setor_drill")

            df_sel_setor = df_raw[df_raw['Setor'] == setor_sel]
            custo_setor = df_sel_setor["Custo_Consumo_R$"].sum()
            consumo_setor = df_sel_setor["Consumo_Mensal_kWh"].sum()

            c_s1, c_s2 = st.columns(2)
            c_s1.metric("Custo do Setor", formatar_br(custo_setor, prefixo="R$ "))
            c_s2.metric("Consumo do Setor", formatar_br(consumo_setor, sufixo=" kWh", decimais=0))

            st.caption(f"Salas que compõem o setor: **{setor_sel}**")

            df_rooms_sector = df_sel_setor.groupby("Id_sala")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_rooms_sector = df_rooms_sector.sort_values("Custo_Consumo_R$", ascending=False)

            st.dataframe(
                df_rooms_sector.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )

            st.divider()

            with st.expander("📊 Ver Ranking Geral de Todos os Setores"):
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
            st.markdown("### 🚪 Salas (Geral)")

            lista_salas = sorted(df_raw['Id_sala'].unique())
            sala_sel = st.selectbox("Selecione a sala:", lista_salas)

            df_sala = df_raw[df_raw['Id_sala'] == sala_sel]
            custo_sala = df_sala["Custo_Consumo_R$"].sum()
            st.metric(f"Custo Total — Sala {sala_sel}", formatar_br(custo_sala, prefixo="R$ "))

            st.dataframe(
                df_sala[["des_nome_equipamento", "Quant", "Potencia_Instalada_kW", "Custo_Consumo_R$"]]
                .sort_values("Custo_Consumo_R$", ascending=False)
                .style.format({
                    "Quant": lambda x: formatar_br(x, decimais=0),
                    "Potencia_Instalada_kW": lambda x: formatar_br(x, decimais=3),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )
        
        st.divider()

        st.markdown("### 🏬 Andares")
        qtd_por_andar = df_raw.groupby('num_andar')['Quant'].sum()
        media_aparelhos = qtd_por_andar.mean() if len(qtd_por_andar)>0 else 0
        st.metric("Média de Aparelhos por Andar", formatar_br(media_aparelhos, sufixo=" un.", decimais=0))

        lista_andares = sorted(df_raw['num_andar'].unique())
        andar_sel = st.selectbox("Selecione o andar:", lista_andares)

        df_andar = df_raw[df_raw['num_andar'] == andar_sel]
        custo_andar = df_andar["Custo_Consumo_R$"].sum()
        st.metric(f"Custo Total — Andar {andar_sel}", formatar_br(custo_andar, prefixo="R$ "))

        df_andar_salas = (
            df_andar.groupby("Id_sala")["Custo_Consumo_R$"]
            .sum().reset_index().sort_values("Custo_Consumo_R$", ascending=False)
        )

        st.dataframe(
            df_andar_salas.style.format({
                "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
            }),
            use_container_width=True, hide_index=True
        )

        st.divider()

        st.markdown("### 🔥❄️ Gasto Relacionado a Aparelhos Térmicos e de Cozinha")
        st.caption("Filtro: Ar Condicionado, Geladeira, Frigobar, Bebedouro, Microondas, Cafeteira, etc.")
        
        target_keywords = [
            "AR CONDICIONADO", "GELADEIRA", "FRIGOBAR", "REFRIGERADOR", 
            "BEBEDOURO", "DESUMIDIFICADOR", "VENTILADOR", "MICROONDAS", 
            "TORRADEIRA", "CAFETEIRA", "CHALEIRA", "FOGÃO", "FORNO", 
            "AQUECEDOR", "FOGAREIRO"
        ]
        
        def is_target_appliance(nome):
            n = str(nome).upper()
            return any(k in n for k in target_keywords)
        
        df_clim = df_raw[df_raw['des_nome_generico_equipamento'].apply(is_target_appliance)].copy()
        
        if not df_clim.empty:
            df_clim_g = df_clim.groupby("des_nome_generico_equipamento")[["Consumo_Mensal_kWh", "Custo_Consumo_R$"]].sum().reset_index()
            df_clim_g = df_clim_g.sort_values("Custo_Consumo_R$", ascending=False)
            
            c_clim1, c_clim2 = st.columns(2)
            c_clim1.metric("Custo Total (Selecionados)", formatar_br(df_clim['Custo_Consumo_R$'].sum(), prefixo="R$ "))
            c_clim2.metric("Consumo Total (Selecionados)", formatar_br(df_clim['Consumo_Mensal_kWh'].sum(), sufixo=" kWh", decimais=0))

            st.dataframe(
                df_clim_g.style.format({
                    "Consumo_Mensal_kWh": lambda x: formatar_br(x, sufixo=" kWh", decimais=0),
                    "Custo_Consumo_R$": lambda x: formatar_br(x, prefixo="R$ ")
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Nenhum equipamento da lista específica foi identificado.")

else:
    st.warning("Carregando dados... Verifique sua conexão.")
