"""
Painel de Adubacao Florestal - Fazenda Santa Vergínia
Repositorio: lubrificacaomaquinassv-cloud/adubacao-florestal-sv

Fluxo:
  1) Upload do KML (mapa) + planilhas de Cobertura e Base/Subsolagem
  2) Parsing e calculo de NPK aplicado
  3) Cruzamento com o cadastro geoespacial de talhoes
  4) Visualizacao: mapa, KPIs, tabelas por retiro, calculadora interativa
  5) Botao opcional para gravar no Supabase (fonte oficial)
"""
import os

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ingestion.kml_parser import ler_talhoes_kml, resumo_por_classe, talhoes_com_codigo_ambiguo
from ingestion.excel_parser import ler_adubacao_cobertura, ler_adubacao_base
from npk_calculator import aplicar_calculadora_no_df, extrair_formula, calcular_npk_aplicado, dose_por_ha

st.set_page_config(page_title="Adubação Florestal - Santa Vergínia", layout="wide")

# Logo da empresa - procura em assets/ (padrão) e na raiz (fallback,
# caso o arquivo tenha sido subido direto na raiz do repositório)
_candidatos_logo = [
    os.path.join(os.path.dirname(__file__), "assets", "logo_santa_verginia.png"),
    os.path.join(os.path.dirname(__file__), "logo_santa_verginia.png"),
    os.path.join(os.path.dirname(__file__), "logo_santa_verginia (1).png"),
]
_logo_path = next((p for p in _candidatos_logo if os.path.exists(p)), None)
if _logo_path:
    st.sidebar.image(_logo_path, use_container_width=True)

# -----------------------------------------------------------------
# Conexao Supabase (opcional - so ativa se as credenciais existirem)
# -----------------------------------------------------------------
def get_engine():
    """Cria a conexao SQLAlchemy com o Supabase via Transaction Pooler,
    lendo as credenciais de st.secrets ou variaveis de ambiente.
    Retorna None se as credenciais nao estiverem configuradas
    (o painel continua funcionando 100% a partir dos uploads)."""
    try:
        from sqlalchemy import create_engine
        url = st.secrets.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
        if not url:
            return None
        return create_engine(url)
    except Exception:
        return None


# -----------------------------------------------------------------
# Sidebar - uploads
# -----------------------------------------------------------------
st.sidebar.title("📂 Fontes de dados")
arq_kml = st.sidebar.file_uploader("Mapa da fazenda (KML)", type=["kml"])
arq_cobertura = st.sidebar.file_uploader("Adubação de Cobertura (xlsx)", type=["xlsx"])
arq_base = st.sidebar.file_uploader("Adubação de Base / Subsolagem (xlsx)", type=["xlsx"])

if not (arq_kml and arq_cobertura and arq_base):
    st.title("🌳 Painel de Adubação Florestal — Fazenda Santa Vergínia")
    st.info("Suba os 3 arquivos na barra lateral (KML + Cobertura + Base) para gerar o painel.")
    st.stop()

# -----------------------------------------------------------------
# Ingestao (cache para nao reprocessar a cada interacao do usuario)
# -----------------------------------------------------------------
@st.cache_data(show_spinner="Lendo o mapa (KML)...")
def _carregar_kml(bytes_kml):
    caminho_tmp = "/tmp/_mapa_fazenda.kml"
    with open(caminho_tmp, "wb") as f:
        f.write(bytes_kml)
    return ler_talhoes_kml(caminho_tmp)


@st.cache_data(show_spinner="Lendo a planilha de Cobertura...")
def _carregar_cobertura(bytes_xlsx):
    caminho_tmp = "/tmp/_cobertura.xlsx"
    with open(caminho_tmp, "wb") as f:
        f.write(bytes_xlsx)
    return ler_adubacao_cobertura(caminho_tmp)


@st.cache_data(show_spinner="Lendo a planilha de Base/Subsolagem...")
def _carregar_base(bytes_xlsx):
    caminho_tmp = "/tmp/_base.xlsx"
    with open(caminho_tmp, "wb") as f:
        f.write(bytes_xlsx)
    return ler_adubacao_base(caminho_tmp)


try:
    gdf_talhoes = _carregar_kml(arq_kml.getvalue())
    df_cobertura = _carregar_cobertura(arq_cobertura.getvalue())
    df_base = _carregar_base(arq_base.getvalue())
except Exception as e:
    st.error(f"Erro ao processar os arquivos: {e}")
    st.stop()

# aplica a calculadora de NPK nas duas planilhas
df_cobertura = aplicar_calculadora_no_df(df_cobertura, "fertilizante", "kg_total", "area_total_ha")
df_base = aplicar_calculadora_no_df(df_base, "fertilizante", "kg_total", "area_plantada_ha")

# -----------------------------------------------------------------
# Cruzamento: talhao (KML) x cobertura x base
# -----------------------------------------------------------------
gdf_validos = gdf_talhoes[gdf_talhoes["talhao"].notna()].copy()

# de-para talhao -> retiro, inferido automaticamente a partir das planilhas
# (cobertura usa nome da aba; base usa a coluna Horto) ate existir um cadastro oficial
de_para_retiro = pd.concat([
    df_cobertura[["talhao", "retiro"]],
    df_base[["talhao", "retiro"]],
]).drop_duplicates(subset="talhao", keep="first")

gdf_validos = gdf_validos.merge(de_para_retiro, on="talhao", how="left")

area_cobertura_talhao = df_cobertura.groupby("talhao").agg(
    area_adubada_cobertura_ha=("area_total_ha", "sum"),
    kg_total_cobertura=("kg_total", "sum"),
    n_kg_cobertura=("N_kg", "sum"),
    p2o5_kg_cobertura=("P2O5_kg", "sum"),
    k2o_kg_cobertura=("K2O_kg", "sum"),
).reset_index()

area_base_feito = df_base[df_base["status"] == "Subsolado/Adubado"].groupby("talhao").agg(
    area_subsolada_ha=("area_plantada_ha", "sum"),
    kg_total_base=("kg_total", "sum"),
).reset_index()

painel = gdf_validos.merge(area_cobertura_talhao, on="talhao", how="left")
painel = painel.merge(area_base_feito, on="talhao", how="left")

for col in ["area_adubada_cobertura_ha", "kg_total_cobertura", "n_kg_cobertura",
            "p2o5_kg_cobertura", "k2o_kg_cobertura", "area_subsolada_ha", "kg_total_base"]:
    painel[col] = painel[col].fillna(0)

painel["pct_cobertura"] = (painel["area_adubada_cobertura_ha"] / painel["area_ha_kml"] * 100).round(1)
painel["pct_base"] = (painel["area_subsolada_ha"] / painel["area_ha_kml"] * 100).round(1)
painel["n_kg_ha_cobertura"] = painel["n_kg_cobertura"] / painel["area_adubada_cobertura_ha"].replace(0, np.nan)
painel["n_kg_ha_cobertura"] = painel["n_kg_ha_cobertura"].round(2)


def status_execucao(pct):
    if pd.isna(pct) or pct == 0:
        return "Não iniciado"
    if pct >= 99:
        return "Completo"
    return "Parcial"


painel["status_cobertura"] = painel["pct_cobertura"].apply(status_execucao)
painel["status_base"] = painel["pct_base"].apply(status_execucao)

# flag de inconsistencia: cobertura feita sem registro de base/subsolagem
painel["alerta_sequencia"] = (painel["pct_cobertura"] > 0) & (painel["pct_base"] == 0)

# -----------------------------------------------------------------
# Sidebar - filtros
# -----------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.title("🔍 Filtros")
retiros_disponiveis = sorted([r for r in painel["retiro"].dropna().unique()])
filtro_retiro = st.sidebar.multiselect("Retiro", options=retiros_disponiveis, default=retiros_disponiveis)
filtro_classe = st.sidebar.multiselect(
    "Classe", options=sorted(painel["classe"].dropna().unique()),
    default=sorted(painel["classe"].dropna().unique())
)

painel_f = painel[painel["retiro"].isin(filtro_retiro) & painel["classe"].isin(filtro_classe)]

# -----------------------------------------------------------------
# Corpo principal
# -----------------------------------------------------------------
st.title("🌳 Painel de Adubação Florestal — Fazenda Santa Vergínia")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Área mapeada (filtro)", f"{painel_f['area_ha_kml'].sum():,.0f} ha")
col2.metric("% Cobertura aplicada", f"{(painel_f['area_adubada_cobertura_ha'].sum() / painel_f['area_ha_kml'].sum() * 100):.1f}%")
col3.metric("% Base/Subsolagem", f"{(painel_f['area_subsolada_ha'].sum() / painel_f['area_ha_kml'].sum() * 100):.1f}%")
col4.metric("Talhões com alerta de sequência", int(painel_f["alerta_sequencia"].sum()))

aba_mapa, aba_cobertura, aba_base, aba_calc, aba_supabase = st.tabs(
    ["🗺️ Mapa", "🌾 Cobertura", "🚜 Base/Subsolagem", "🧮 Calculadora NPK", "☁️ Supabase"]
)

# --- Mapa ---
with aba_mapa:
    ambiguos = talhoes_com_codigo_ambiguo(gdf_talhoes)
    if len(ambiguos) > 0:
        with st.expander(f"⚠️ {ambiguos['talhao'].nunique()} códigos de talhão aparecem em mais de uma classe (verificar com o coordenador)"):
            st.caption(
                "O cruzamento abaixo usa apenas o número do talhão. Para estes códigos, "
                "existe mais de um polígono no KML com o mesmo número em classes diferentes "
                "(ex: Silvicultura e Silvipastoril) — o valor de área/adubação pode estar "
                "sendo atribuído à classe errada até isso ser confirmado."
            )
            st.dataframe(ambiguos, use_container_width=True)

    variavel_cor = st.radio(
        "Colorir talhões por:",
        ["Status Cobertura", "Status Base/Subsolagem", "Dose de N (kg/ha) - Cobertura"],
        horizontal=True,
        key="variavel_cor_mapa",
    )

    cores_status = {"Completo": "#2e7d32", "Parcial": "#f9a825", "Não iniciado": "#c62828"}

    def _cor_da_linha(row):
        if variavel_cor == "Status Cobertura":
            return cores_status.get(row["status_cobertura"], "#999999")
        if variavel_cor == "Status Base/Subsolagem":
            return cores_status.get(row["status_base"], "#999999")
        n = row["n_kg_ha_cobertura"]
        if pd.isna(n) or n == 0:
            return "#c62828"
        return "#f9a825" if n < 10 else "#2e7d32"

    @st.cache_resource(show_spinner="Montando o mapa...")
    def montar_mapa(_gdf, variavel_cor_key):
        """
        Monta o mapa como UM UNICO GeoJson (FeatureCollection), em vez de um
        folium.GeoJson por talhao. Com ~700+ talhoes, criar uma camada por
        talhao sobrecarrega o DOM do navegador e causa o erro
        'NotFoundError: removeChild' no Streamlit Cloud. Um unico layer com
        varias features resolve isso e tambem carrega mais rapido.
        """
        gdf_mapa = _gdf.copy()
        gdf_mapa["cor"] = gdf_mapa.apply(_cor_da_linha, axis=1)
        gdf_mapa["popup_html"] = gdf_mapa.apply(
            lambda row: (
                f"Talhão {row['talhao']} ({row['classe']})<br>"
                f"Retiro: {row['retiro'] or '-'}<br>"
                f"Área: {row['area_ha_kml']:.1f} ha<br>"
                f"Cobertura: {row['pct_cobertura']:.0f}% ({row['status_cobertura']})<br>"
                f"Base: {row['pct_base']:.0f}% ({row['status_base']})<br>"
                f"N aplicado: {row['n_kg_ha_cobertura'] if pd.notna(row['n_kg_ha_cobertura']) else '-'} kg/ha"
            ),
            axis=1,
        )

        centro = [gdf_mapa.geometry.centroid.y.mean(), gdf_mapa.geometry.centroid.x.mean()]
        mapa = folium.Map(location=centro, zoom_start=12, tiles="OpenStreetMap")

        folium.GeoJson(
            gdf_mapa[["talhao", "cor", "popup_html", "geometry"]].__geo_interface__,
            style_function=lambda feature: {
                "fillColor": feature["properties"]["cor"],
                "color": "#333",
                "weight": 1,
                "fillOpacity": 0.6,
            },
            tooltip=folium.GeoJsonTooltip(fields=["talhao"], aliases=["Talhão:"]),
            popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=250),
        ).add_to(mapa)

        return mapa

    mapa = montar_mapa(painel_f, variavel_cor)
    st_folium(mapa, width=1200, height=600, returned_objects=[], key="mapa_talhoes")

# --- Cobertura ---
with aba_cobertura:
    resumo_retiro_cob = painel_f.groupby("retiro").agg(
        area_total_ha=("area_ha_kml", "sum"),
        area_adubada_ha=("area_adubada_cobertura_ha", "sum"),
        talhoes_nao_iniciados=("status_cobertura", lambda s: (s == "Não iniciado").sum()),
    ).reset_index()
    resumo_retiro_cob["pct_execucao"] = (resumo_retiro_cob["area_adubada_ha"] / resumo_retiro_cob["area_total_ha"] * 100).round(1)
    resumo_retiro_cob = resumo_retiro_cob.sort_values("pct_execucao")

    st.subheader("Execução por retiro (Cobertura)")
    st.dataframe(resumo_retiro_cob, use_container_width=True)

    st.subheader("Detalhe por talhão")
    st.dataframe(
        painel_f[["talhao", "retiro", "classe", "area_ha_kml", "area_adubada_cobertura_ha",
                  "pct_cobertura", "status_cobertura", "n_kg_ha_cobertura"]].sort_values("pct_cobertura"),
        use_container_width=True,
    )

    st.subheader("Lançamentos brutos (planilha de Cobertura)")
    st.dataframe(df_cobertura, use_container_width=True)

# --- Base/Subsolagem ---
with aba_base:
    resumo_retiro_base = painel_f.groupby("retiro").agg(
        area_total_ha=("area_ha_kml", "sum"),
        area_subsolada_ha=("area_subsolada_ha", "sum"),
    ).reset_index()
    resumo_retiro_base["pct_execucao"] = (resumo_retiro_base["area_subsolada_ha"] / resumo_retiro_base["area_total_ha"] * 100).round(1)
    resumo_retiro_base = resumo_retiro_base.sort_values("pct_execucao")

    st.subheader("Execução por retiro (Base/Subsolagem)")
    st.dataframe(resumo_retiro_base, use_container_width=True)

    st.subheader("Pendências (\"A subsolar\")")
    st.dataframe(df_base[df_base["status"] == "A subsolar"], use_container_width=True)

    st.subheader("Já subsolado/adubado")
    st.dataframe(df_base[df_base["status"] == "Subsolado/Adubado"], use_container_width=True)

# --- Calculadora NPK ---
with aba_calc:
    st.subheader("Calculadora de NPK aplicado")
    c1, c2, c3, c4 = st.columns(4)
    kg_input = c1.number_input("Quantidade de adubo (kg)", min_value=0.0, value=239.0, step=10.0)
    n_input = c2.number_input("% N", min_value=0, max_value=100, value=14)
    p_input = c3.number_input("% P₂O₅", min_value=0, max_value=100, value=14)
    k_input = c4.number_input("% K₂O", min_value=0, max_value=100, value=10)
    area_input = st.number_input("Área aplicada (ha) — opcional, para calcular dose/ha", min_value=0.0, value=0.0, step=1.0)

    if st.button("Calcular"):
        resultado = calcular_npk_aplicado(kg_input, n_input, p_input, k_input)
        st.success(
            f"N: {resultado['N_kg']} kg  |  P₂O₅: {resultado['P2O5_kg']} kg  |  K₂O: {resultado['K2O_kg']} kg"
        )
        if area_input > 0:
            dose = dose_por_ha(kg_input, area_input, n_input, p_input, k_input)
            st.info(
                f"Dose por hectare — N: {dose['N_kg_ha']} kg/ha | "
                f"P₂O₅: {dose['P2O5_kg_ha']} kg/ha | K₂O: {dose['K2O_kg_ha']} kg/ha"
            )

    st.markdown("---")
    st.subheader("NPK calculado automaticamente — todos os lançamentos de Cobertura")
    st.dataframe(
        df_cobertura[["talhao", "retiro", "fertilizante", "formula_npk", "kg_total",
                      "N_kg", "P2O5_kg", "K2O_kg", "N_kg_ha", "P2O5_kg_ha", "K2O_kg_ha"]],
        use_container_width=True,
    )

    nao_identificados = df_cobertura[df_cobertura["formula_npk"] == "não identificada"]["fertilizante"].unique()
    if len(nao_identificados) > 0:
        st.warning(f"Fertilizantes sem fórmula reconhecida (cadastrar em FORMULAS_ADUBO): {list(nao_identificados)}")

# --- Supabase ---
with aba_supabase:
    st.subheader("Gravar no Supabase")
    engine = get_engine()
    if engine is None:
        st.warning(
            "Conexão com Supabase não configurada. Defina `SUPABASE_DB_URL` em `.streamlit/secrets.toml` "
            "(local) ou nos Secrets do Streamlit Cloud (produção) para habilitar a gravação."
        )
        st.code(
            'SUPABASE_DB_URL = "postgresql+psycopg://postgres.<ref>:<senha>@'
            'aws-1-sa-east-1.pooler.supabase.com:6543/postgres"',
            language="toml",
        )
    else:
        st.success("Conexão com Supabase disponível.")
        if st.button("Gravar talhões + cobertura + base no banco"):
            try:
                talhoes_out = painel[["talhao", "classe", "retiro", "area_ha_kml"]].copy()
                talhoes_out["geom"] = painel.geometry.apply(lambda g: g.wkt)
                talhoes_out.to_sql("dim_talhao_florestal", engine, if_exists="append", index=False)
                df_cobertura.to_sql("fato_adubacao_cobertura", engine, if_exists="append", index=False)
                df_base.to_sql("fato_adubacao_base", engine, if_exists="append", index=False)
                st.success("Dados gravados com sucesso no Supabase.")
            except Exception as e:
                st.error(f"Erro ao gravar: {e}")

st.sidebar.markdown("---")
st.sidebar.caption(f"Talhões no mapa: {len(gdf_talhoes)} | Com número válido: {gdf_validos['talhao'].nunique()}")
