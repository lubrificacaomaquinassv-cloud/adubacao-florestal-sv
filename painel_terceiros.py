"""
Componente Streamlit — Operações florestais de terceiros (drone/pulverização).
Importar em app.py do painel de Adubação Florestal.
"""
from __future__ import annotations

import json
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ingestion_terceiros.excel_terceiros_parser import ler_pasta_terceiros, ler_arquivo_terceiros
from ingestion_terceiros.validacao_terceiros import resumo_validacao, validar_operacoes

CORES_PRESTADOR = {
    "COSER": "#2196F3",
    "F-ORION": "#FF9800",
    "ECOAERO": "#4CAF50",
}


def carregar_terceiros(origem) -> pd.DataFrame:
    """origem: Path da pasta, caminho de arquivo, bytes de xlsx ou list[UploadedFile]."""
    if isinstance(origem, (str, Path)):
        p = Path(origem)
        if p.is_dir():
            return ler_pasta_terceiros(p)
        return ler_arquivo_terceiros(p)

    if isinstance(origem, bytes):
        tmp = Path("/tmp/_terceiros_upload.xlsx")
        tmp.write_bytes(origem)
        return ler_arquivo_terceiros(tmp)

    # Streamlit UploadedFile(s)
    partes = []
    for arq in origem:
        tmp = Path(f"/tmp/_terceiros_{arq.name}")
        tmp.write_bytes(arq.getvalue())
        partes.append(ler_arquivo_terceiros(tmp))
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True).drop_duplicates(subset=["hash_registro"])


def cruzar_com_mapa(gdf_talhoes: pd.DataFrame, df_ops: pd.DataFrame) -> pd.DataFrame:
    """Agrega operações por talhao_codigo e faz merge com GeoDataFrame de talhões."""
    if df_ops.empty or gdf_talhoes is None or len(gdf_talhoes) == 0:
        return gdf_talhoes

    agg = df_ops.groupby("talhao_codigo", dropna=False).agg(
        ha_aplicado_terceiros=("ha_aplicado", "sum"),
        valor_total_terceiros=("valor_total", lambda s: s.fillna(0).sum()),
        qtd_operacoes=("hash_registro", "count"),
        prestadores=("prestador", lambda s: ", ".join(sorted(s.dropna().unique()))),
        operacoes=("operacao_realizada", lambda s: " | ".join(sorted(set(x for x in s.dropna().unique() if x)))),
        hortos=("horto", lambda s: ", ".join(sorted(set(x for x in s.dropna().unique() if x)))),
    ).reset_index()

    gdf = gdf_talhoes.copy()
    gdf["talhao_join"] = gdf["talhao"].astype(str).str.strip().str.upper()
    agg["talhao_join"] = agg["talhao_codigo"].astype(str).str.strip().str.upper()

    merged = gdf.merge(agg, on="talhao_join", how="left")
    for col in ["ha_aplicado_terceiros", "valor_total_terceiros", "qtd_operacoes"]:
        merged[col] = merged[col].fillna(0)
    merged["pct_terceiros"] = (
        merged["ha_aplicado_terceiros"] / merged["area_ha_kml"].replace(0, np.nan) * 100
    ).round(1)
    return merged


def render_aba_terceiros(
    df_ops: pd.DataFrame,
    gdf_talhoes=None,
    get_engine=None,
):
    """Renderiza a aba completa de operações terceiros."""
    if df_ops.empty:
        st.info("Nenhuma planilha de terceiros carregada. Use o upload na barra lateral.")
        return

    alertas = validar_operacoes(df_ops)
    resumo = resumo_validacao(df_ops, alertas)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Lançamentos", resumo["total_registros"])
    c2.metric("ha aplicado", f"{resumo['ha_aplicado_total']:,.1f}")
    c3.metric("Valor total (R$)", f"R$ {resumo['valor_total_rs']:,.2f}")
    c4.metric("Alertas", resumo["total_alertas"])
    c5.metric("Válidos", resumo["registros_validos"])

    sub_mapa, sub_tabela, sub_valid, sub_lovable = st.tabs(
        ["Mapa GIS", "Tabelas", "Validação", "Lovable / Supabase"]
    )

    with sub_valid:
        if resumo["alertas_erro"]:
            st.error(f"{resumo['alertas_erro']} erro(s) — corrija antes de publicar no Supabase.")
        if resumo["alertas_aviso"]:
            st.warning(f"{resumo['alertas_aviso']} aviso(s) de qualidade de dados.")
        if len(alertas):
            filtro_sev = st.multiselect(
                "Filtrar severidade",
                options=["ERRO", "AVISO", "INFO"],
                default=["ERRO", "AVISO"],
            )
            st.dataframe(
                alertas[alertas["severidade"].isin(filtro_sev)],
                use_container_width=True,
            )
        else:
            st.success("Nenhum alerta de validação.")

    with sub_tabela:
        filtro_prest = st.multiselect(
            "Prestador",
            options=sorted(df_ops["prestador"].dropna().unique()),
            default=sorted(df_ops["prestador"].dropna().unique()),
        )
        df_f = df_ops[df_ops["prestador"].isin(filtro_prest)]

        st.subheader("Por prestador e mês")
        resumo_prest = (
            df_f.groupby(["prestador", "periodo_mes"], dropna=False)
            .agg(
                lancamentos=("hash_registro", "count"),
                ha_aplicado=("ha_aplicado", "sum"),
                valor_total=("valor_total", lambda s: s.fillna(0).sum()),
            )
            .reset_index()
            .sort_values(["prestador", "periodo_mes"])
        )
        st.dataframe(resumo_prest, use_container_width=True)

        st.subheader("Por horto")
        resumo_horto = (
            df_f.groupby(["horto", "prestador"], dropna=False)
            .agg(ha_aplicado=("ha_aplicado", "sum"), lancamentos=("hash_registro", "count"))
            .reset_index()
            .sort_values("ha_aplicado", ascending=False)
        )
        st.dataframe(resumo_horto, use_container_width=True)

        st.subheader("Detalhe dos lançamentos")
        cols_show = [
            "prestador", "operacao_realizada", "produto", "horto", "talhao_raw",
            "ha_aplicado", "tarifa_rs_ha", "valor_total", "data_inicio", "periodo_mes",
            "arquivo_origem",
        ]
        st.dataframe(df_f[cols_show].sort_values(["data_inicio", "prestador"], ascending=[False, True]), use_container_width=True)

        eco = df_f[df_f["prestador"] == "ECOAERO"]
        if len(eco):
            st.subheader("EcoAero — doses por produto (ha)")
            with st.expander("Ver produtos_por_ha"):
                for _, row in eco.iterrows():
                    st.markdown(f"**Talhão {row['talhao_raw']}** — {row.get('data_inicio', '')}")
                    if row.get("produtos_por_ha"):
                        st.json(row["produtos_por_ha"])

    with sub_mapa:
        if gdf_talhoes is None or len(gdf_talhoes) == 0:
            st.warning("Carregue o KML na barra lateral para exibir o mapa GIS.")
        else:
            painel_mapa = cruzar_com_mapa(gdf_talhoes, df_ops)
            variavel = st.radio(
                "Colorir por",
                ["Prestador (última operação)", "ha aplicado (terceiros)", "Status cobertura"],
                horizontal=True,
            )

            def cor_linha(row):
                if variavel == "ha aplicado (terceiros)":
                    ha = row.get("ha_aplicado_terceiros", 0)
                    if ha <= 0:
                        return "#555555"
                    if ha >= (row.get("area_ha_kml") or 0) * 0.99:
                        return "#2e7d32"
                    return "#f9a825"
                if variavel == "Status cobertura":
                    pct = row.get("pct_terceiros", 0)
                    if pct <= 0:
                        return "#555555"
                    if pct >= 99:
                        return "#2e7d32"
                    return "#f9a825"
                # prestador — pega último do df_ops para o talhão
                cod = row.get("talhao")
                ops = df_ops[df_ops["talhao_codigo"] == str(cod)]
                if ops.empty:
                    return "#555555"
                prest = ops.iloc[-1]["prestador"]
                return CORES_PRESTADOR.get(prest, "#999999")

            gdf_mapa = painel_mapa[painel_mapa["talhao"].notna()].copy()
            gdf_mapa["cor"] = gdf_mapa.apply(cor_linha, axis=1)
            gdf_mapa["popup_html"] = gdf_mapa.apply(
                lambda r: (
                    f"Talhão {r['talhao']} ({r.get('classe', '-')})<br>"
                    f"Área KML: {r.get('area_ha_kml', 0):.1f} ha<br>"
                    f"ha terceiros: {r.get('ha_aplicado_terceiros', 0):.1f}<br>"
                    f"Prestadores: {r.get('prestadores', '-') or '-'}<br>"
                    f"Operações: {r.get('operacoes', '-') or '-'}"
                ),
                axis=1,
            )

            centro = [gdf_mapa.geometry.centroid.y.mean(), gdf_mapa.geometry.centroid.x.mean()]
            mapa = folium.Map(location=centro, zoom_start=12, tiles="OpenStreetMap")
            folium.GeoJson(
                gdf_mapa[["talhao", "cor", "popup_html", "geometry"]].__geo_interface__,
                style_function=lambda f: {
                    "fillColor": f["properties"]["cor"],
                    "color": "#333",
                    "weight": 1,
                    "fillOpacity": 0.65,
                },
                tooltip=folium.GeoJsonTooltip(fields=["talhao"], aliases=["Talhão:"]),
                popup=folium.GeoJsonPopup(fields=["popup_html"], labels=False, max_width=280),
            ).add_to(mapa)

            st_folium(mapa, width=1200, height=600, returned_objects=[], key="mapa_terceiros")

            sem_mapa = df_ops[~df_ops["talhao_codigo"].isin(gdf_mapa["talhao"].astype(str))]
            if len(sem_mapa):
                with st.expander(f"⚠️ {len(sem_mapa)} lançamentos sem polígono no KML"):
                    st.dataframe(
                        sem_mapa[["prestador", "talhao_raw", "horto", "ha_aplicado", "operacao_realizada"]],
                        use_container_width=True,
                    )

    with sub_lovable:
        st.markdown("""
**Views prontas para Lovable** (após gravar no Supabase):

| View | Uso |
|------|-----|
| `vw_api_terceiros_drone` | Listagem flat (API REST via PostgREST) |
| `vw_terceiros_drone_resumo_prestador` | KPIs por prestador/mês |
| `vw_terceiros_drone_por_horto` | Resumo por horto |
| `vw_terceiros_drone_por_talhao` | Agregado por talhão (mapa) |
| `vw_terceiros_drone_mapa` | Join com `dim_talhoes` (KML) |
        """)

        st.subheader("Preview JSON (vw_api_terceiros_drone)")
        preview = df_ops.head(50).copy()
        if "produtos_por_ha" in preview.columns:
            preview["produtos_por_ha"] = preview["produtos_por_ha"].apply(
                lambda x: x if isinstance(x, dict) else None
            )
        st.json(json.loads(preview.to_json(orient="records", date_format="iso")))

        if get_engine is None:
            st.warning("Supabase não configurado.")
        else:
            engine = get_engine()
            if engine is None:
                st.warning("Defina SUPABASE_DB_URL para gravar.")
            elif st.button("Gravar operações terceiros no Supabase"):
                try:
                    import json as json_mod
                    df_db = df_ops.copy()
                    df_db["data_inicio"] = pd.to_datetime(df_db["data_inicio"], errors="coerce")
                    df_db["produtos_por_ha"] = df_db["produtos_por_ha"].apply(
                        lambda x: json_mod.dumps(x, ensure_ascii=False) if isinstance(x, dict) else None
                    )
                    cols = [c for c in df_db.columns if c in df_ops.columns]
                    df_db[cols].to_sql(
                        "operacoes_florestais_terceiros_drone",
                        engine,
                        if_exists="append",
                        index=False,
                    )
                    st.success("Dados gravados. Execute sql/002_views_lovable_terceiros_drone.sql se ainda não aplicou.")
                except Exception as exc:
                    st.error(f"Erro ao gravar: {exc}")
