"""
Parser do mapa da fazenda (KML) -> DataFrame de talhões.

Le a pasta "Talhoes (TIP / Silvipastoril / Silvicultura / Pastagem)" do KML
exportado (ex: fazenda_santa_virginia_completo.kml), que contem 4 subpastas
por classe de uso do solo: Silvicultura, Silvipastoril, Pastagem, TIP.

Cada Placemark tem, no <description>, um bloco HTML com:
    Numero: <codigo do talhao>
    Classe: <Silvicultura|Silvipastoril|Pastagem|TIP>
    Area: <area em ha, calculada no software de origem>
    Imovel: ...
    Certificado: ...

Ignora as subpastas "* - Labels" (sao apenas rotulos/pontos, nao poligonos).
"""
import re
import xml.etree.ElementTree as ET

import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon

NS = {"k": "http://www.opengis.net/kml/2.2"}

PASTA_TALHOES = "Talhões (TIP / Silvipastoril / Silvicultura / Pastagem)"
CLASSES_VALIDAS = ["Silvicultura", "Silvipastoril", "Pastagem", "TIP"]

RE_NUMERO = re.compile(r"Número:</b>\s*([^<]+)")
RE_CLASSE = re.compile(r"Classe:</b>\s*([^<]+)")
RE_AREA = re.compile(r"Área:</b>\s*([\d.,]+)\s*ha")


def _find_folder(elem, nome):
    """Busca uma subpasta <Folder> pelo nome (nao recursivo, so um nivel)."""
    for f in elem.findall("k:Folder", NS):
        n = f.find("k:name", NS)
        if n is not None and n.text == nome:
            return f
    return None


def _parse_description(desc_html: str) -> dict:
    """Extrai numero, classe e area do HTML embutido no <description>."""
    numero = RE_NUMERO.search(desc_html)
    classe = RE_CLASSE.search(desc_html)
    area = RE_AREA.search(desc_html)
    return {
        "talhao": numero.group(1).strip() if numero else None,
        "classe": classe.group(1).strip() if classe else None,
        "area_ha_kml": float(area.group(1).replace(",", ".")) if area else None,
    }


def _parse_coordinates(coord_text: str) -> list:
    """Converte a string de coordenadas do KML (lon,lat,alt lon,lat,alt ...) em lista de tuplas (lon, lat)."""
    pontos = []
    for grupo in coord_text.strip().split():
        partes = grupo.split(",")
        lon, lat = float(partes[0]), float(partes[1])
        pontos.append((lon, lat))
    return pontos


def ler_talhoes_kml(caminho_kml: str) -> gpd.GeoDataFrame:
    """
    Le o KML e retorna um GeoDataFrame com um registro por talhao:
    talhao, classe, area_ha_kml, geometry (WGS84 / EPSG:4326).

    Talhoes sem "Numero" valido (ex: algumas poligonos de TIP/reserva legal
    que nao tem numero de talhao agricola) ficam com talhao=None e sao
    mantidos no retorno - quem usa a funcao decide se filtra ou nao.
    """
    tree = ET.parse(caminho_kml)
    root = tree.getroot()
    doc = root.find("k:Document", NS)

    pasta_talhoes = _find_folder(doc, PASTA_TALHOES)
    if pasta_talhoes is None:
        raise ValueError(
            f"Pasta '{PASTA_TALHOES}' nao encontrada no KML. "
            "Confira o nome exato da pasta no arquivo de origem."
        )

    registros = []
    for subpasta in pasta_talhoes.findall("k:Folder", NS):
        nome_subpasta = subpasta.find("k:name", NS).text
        if nome_subpasta not in CLASSES_VALIDAS:
            continue  # pula "* - Labels"

        for placemark in subpasta.findall("k:Placemark", NS):
            desc_el = placemark.find("k:description", NS)
            poly_el = placemark.find(".//k:Polygon", NS)
            if desc_el is None or poly_el is None:
                continue

            info = _parse_description(desc_el.text or "")

            coords_el = poly_el.find(".//k:coordinates", NS)
            if coords_el is None or not coords_el.text:
                continue
            pontos = _parse_coordinates(coords_el.text)
            if len(pontos) < 3:
                continue

            registros.append({
                "talhao": info["talhao"],
                "classe": info["classe"] or nome_subpasta,
                "area_ha_kml": info["area_ha_kml"],
                "geometry": Polygon(pontos),
            })

    gdf = gpd.GeoDataFrame(registros, geometry="geometry", crs="EPSG:4326")

    # Normaliza codigo do talhao (string, sem espacos, upper) para casar com as planilhas
    gdf["talhao"] = gdf["talhao"].astype(str).str.strip().str.upper()
    gdf.loc[gdf["talhao"].isin(["NAN", "NONE", ""]), "talhao"] = None

    # Remove duplicatas exatas de digitalizacao: mesmo talhao + mesma classe + mesma
    # area (poligono desenhado 2x por engano no software de origem). Mantem so 1.
    gdf = gdf.drop_duplicates(subset=["talhao", "classe", "area_ha_kml"], keep="first").reset_index(drop=True)

    return gdf


def talhoes_com_codigo_ambiguo(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Retorna os codigos de talhao que aparecem em MAIS DE UMA classe
    (ex: talhao "17" existe tanto em Silvicultura quanto em Silvipastoril,
    com areas diferentes). Nesse caso, cruzar uma planilha com o KML usando
    so o numero do talhao e ambiguo - e preciso confirmar com o coordenador
    a qual classe cada lancamento da planilha se refere.
    """
    v = gdf[gdf["talhao"].notna()]
    contagem = v.groupby("talhao")["classe"].nunique()
    codigos_ambiguos = contagem[contagem > 1].index
    return v[v["talhao"].isin(codigos_ambiguos)][["talhao", "classe", "area_ha_kml"]].sort_values("talhao")


def resumo_por_classe(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Contagem de talhoes e area total por classe (Silvicultura, Silvipastoril, Pastagem, TIP)."""
    return (
        gdf.groupby("classe")
        .agg(qtd_talhoes=("talhao", "count"), area_total_ha=("area_ha_kml", "sum"))
        .reset_index()
        .sort_values("area_total_ha", ascending=False)
    )


if __name__ == "__main__":
    import sys
    gdf = ler_talhoes_kml(sys.argv[1] if len(sys.argv) > 1 else "fazenda_santa_virginia_completo.kml")
    print(f"Total de poligonos lidos: {len(gdf)}")
    print(f"Talhoes com numero valido: {gdf['talhao'].notna().sum()}")
    print(resumo_por_classe(gdf))
    print(gdf.head(10)[["talhao", "classe", "area_ha_kml"]])
