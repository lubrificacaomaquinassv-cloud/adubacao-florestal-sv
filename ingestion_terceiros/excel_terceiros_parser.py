"""
Parsers das planilhas de terceiros — COSER, F-ORION e EcoAero.

Formato comum (COSER / F-ORION):
  Cabeçalho na linha com "Operação Realizada" + "Talhão" + "há aplicado".
  Dados abaixo até linha de totais ou fim da aba.

EcoAero (Taquarussu):
  Cabeçalho "Talhão" + "Produto por há" com nomes de produtos na linha seguinte.
  Horto fixo: Taquarussu.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import pandas as pd

SCHEMA_COLUNAS = [
    "prestador",
    "operacao_realizada",
    "produto",
    "horto",
    "talhao_raw",
    "talhao_codigo",
    "ha_total",
    "ha_aplicado",
    "data_inicio",
    "tarifa_rs_ha",
    "valor_total",
    "recomendacao",
    "volume_calda",
    "area_floresta_ha",
    "produtos_por_ha",
    "observacao",
    "periodo_mes",
    "periodo_ano",
    "periodo_mes_num",
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "hash_registro",
]

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

PRESTADOR_PASTA = {
    "coser": "COSER",
    "f-orion": "F-ORION",
    "forion": "F-ORION",
    "ecoaero": "ECOAERO",
}


def _ascii_header(val) -> str:
    """Normaliza rótulo de cabeçalho (acentos, mojibake, espaços)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("�", "").replace("ã", "a").replace("á", "a").replace("é", "e").replace("í", "i")
    s = s.replace("ó", "o").replace("ú", "u").replace("ç", "c")
    return re.sub(r"\s+", " ", s)


def _norm_txt(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "xxx") else None


def _norm_horto(val) -> str | None:
    s = _norm_txt(val)
    if not s:
        return None
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip()


def _to_num(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(".", "").replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in (".", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_date(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str) and val.lower() in MESES:
        return None
    dt = pd.to_datetime(val, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        return None
    if dt.year < 2000:
        return None
    return dt.date()


def _talhao_codigo(talhao_raw: str | None) -> str | None:
    """Extrai código principal do talhão para cruzamento com KML (ex: '392/393' -> '392')."""
    if not talhao_raw:
        return None
    s = talhao_raw.upper().strip()
    nums = re.findall(r"\d+", s)
    return nums[0] if nums else s


def _hash_registro(row: dict) -> str:
    chave = "|".join(
        str(row.get(c, "") or "")
        for c in [
            "prestador", "operacao_realizada", "produto", "horto",
            "talhao_raw", "ha_aplicado", "data_inicio", "valor_total",
            "arquivo_origem", "linha_origem",
        ]
    )
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:32]


def _detectar_prestador(path: Path) -> str:
    partes = [p.lower() for p in path.parts]
    for chave, nome in PRESTADOR_PASTA.items():
        if any(chave in p for p in partes):
            return nome
    nome = path.stem.lower()
    if "coser" in nome:
        return "COSER"
    if "ecoaero" in nome or "lagarta" in nome:
        return "ECOAERO"
    return "F-ORION"


def _extrair_periodo(raw: pd.DataFrame, path: Path) -> tuple[str | None, int | None, int | None]:
    texto = " ".join(
        str(x)
        for x in raw.iloc[:6, :].values.flatten()
        if pd.notna(x)
    ).lower()
    m = re.search(r"per[ií]odo:\s*(\w+)\s*/\s*(\d{4})", texto, re.I)
    if m:
        mes_nome = m.group(1).lower()
        ano = int(m.group(2))
        mes_num = MESES.get(mes_nome)
        if mes_num:
            return f"{ano}-{mes_num:02d}", ano, mes_num
    m2 = re.search(r"(\d{4})", path.stem)
    ano = int(m2.group(1)) if m2 else None
    for mes_nome, mes_num in MESES.items():
        if mes_nome in path.stem.lower():
            if ano:
                return f"{ano}-{mes_num:02d}", ano, mes_num
            return None, None, mes_num
    return None, ano, None


def _find_header_row(raw: pd.DataFrame) -> tuple[int, int] | None:
    """Retorna (linha_header, col_offset) para layout COSER/F-ORION."""
    for i in range(min(15, len(raw))):
        row = raw.iloc[i]
        for offset in (0, 1):
            vals = [_ascii_header(v) for v in row.iloc[offset : offset + 14]]
            joined = " ".join(vals)
            if (
                ("oper" in joined and "realiz" in joined)
                and "talh" in joined
                and "aplic" in joined
            ):
                return i, offset
    return None


def _parse_coser_forion(raw: pd.DataFrame, path: Path, aba: str, prestador: str) -> list[dict]:
    header_info = _find_header_row(raw)
    if header_info is None:
        return []

    linha_header, offset = header_info
    periodo_mes, periodo_ano, periodo_mes_num = _extrair_periodo(raw, path)

    col_map = {}
    header = raw.iloc[linha_header]
    for j in range(offset, min(offset + 16, len(header))):
        low = _ascii_header(header.iloc[j])
        if not low:
            continue
        if "oper" in low and "realiz" in low:
            col_map["operacao_realizada"] = j
        elif low == "produto":
            col_map["produto"] = j
        elif "recomend" in low:
            col_map["recomendacao"] = j
        elif "volume" in low and "calda" in low:
            col_map["volume_calda"] = j
        elif low == "horto":
            col_map["horto"] = j
        elif "talh" in low:
            col_map["talhao_raw"] = j
        elif "total" in low and "aplic" not in low and ("ha" in low or "h " in low):
            col_map["ha_total"] = j
        elif "aplic" in low:
            col_map["ha_aplicado"] = j
        elif "data" in low and "inic" in low:
            col_map["data_inicio"] = j
        elif "tarifa" in low:
            col_map["tarifa_rs_ha"] = j
        elif "valor" in low and "total" in low:
            col_map["valor_total"] = j
        elif "observ" in low:
            col_map["observacao"] = j

    if "talhao_raw" not in col_map or "ha_aplicado" not in col_map:
        return []

    registros = []
    operacao_atual = None
    produto_atual = None

    for i in range(linha_header + 1, len(raw)):
        row = raw.iloc[i]
        talhao = _norm_txt(row.iloc[col_map["talhao_raw"]]) if "talhao_raw" in col_map else None
        ha_aplicado = _to_num(row.iloc[col_map["ha_aplicado"]]) if "ha_aplicado" in col_map else None

        if not talhao and ha_aplicado is None:
            continue
        if talhao and talhao.lower() in ("total", "totais", "consumo total"):
            break
        if not talhao:
            continue

        op = _norm_txt(row.iloc[col_map["operacao_realizada"]]) if "operacao_realizada" in col_map else None
        prod = _norm_txt(row.iloc[col_map["produto"]]) if "produto" in col_map else None
        if op:
            operacao_atual = op
        if prod:
            produto_atual = prod

        operacao = op or operacao_atual
        produto = prod or produto_atual

        if operacao and operacao.lower() in ("abastecimento", "gasolina"):
            continue
        if ha_aplicado is None or ha_aplicado <= 0:
            continue

        reg = {
            "prestador": prestador,
            "operacao_realizada": operacao,
            "produto": produto,
            "horto": _norm_horto(row.iloc[col_map["horto"]]) if "horto" in col_map else None,
            "talhao_raw": talhao.upper(),
            "talhao_codigo": _talhao_codigo(talhao),
            "ha_total": _to_num(row.iloc[col_map["ha_total"]]) if "ha_total" in col_map else None,
            "ha_aplicado": ha_aplicado,
            "data_inicio": _to_date(row.iloc[col_map["data_inicio"]]) if "data_inicio" in col_map else None,
            "tarifa_rs_ha": _to_num(row.iloc[col_map["tarifa_rs_ha"]]) if "tarifa_rs_ha" in col_map else None,
            "valor_total": _to_num(row.iloc[col_map["valor_total"]]) if "valor_total" in col_map else None,
            "recomendacao": _norm_txt(row.iloc[col_map["recomendacao"]]) if "recomendacao" in col_map else None,
            "volume_calda": _norm_txt(row.iloc[col_map["volume_calda"]]) if "volume_calda" in col_map else None,
            "area_floresta_ha": None,
            "produtos_por_ha": None,
            "observacao": _norm_txt(row.iloc[col_map["observacao"]]) if "observacao" in col_map else None,
            "periodo_mes": periodo_mes,
            "periodo_ano": periodo_ano,
            "periodo_mes_num": periodo_mes_num,
            "arquivo_origem": path.name,
            "aba_origem": aba,
            "linha_origem": i + 1,
        }
        reg["hash_registro"] = _hash_registro(reg)
        registros.append(reg)

    return registros


def _parse_ecoaero(raw: pd.DataFrame, path: Path, aba: str) -> list[dict]:
    linha_header = None
    for i in range(min(10, len(raw))):
        row = raw.iloc[i]
        vals = [_ascii_header(v) for v in row]
        if any("talh" in v for v in vals) and any("produto" in v for v in vals):
            linha_header = i
            break
    if linha_header is None:
        return []

    header = raw.iloc[linha_header]
    prod_row = raw.iloc[linha_header + 1]

    col_talhao = col_area = col_data = col_calda = None
    prod_cols: dict[int, str] = {}

    for j, val in enumerate(header):
        low = _ascii_header(val)
        if not low:
            continue
        if "talh" in low:
            col_talhao = j
        elif "floresta" in low:
            col_area = j
        elif low == "data":
            col_data = j
        elif "calda" in low:
            col_calda = j

    for j, val in enumerate(prod_row):
        nome = _norm_txt(val)
        if nome and j > (col_data or 0):
            prod_cols[j] = nome

    if col_talhao is None:
        return []

    registros = []
    for i in range(linha_header + 2, len(raw)):
        row = raw.iloc[i]
        talhao = _norm_txt(row.iloc[col_talhao])
        if not talhao:
            continue

        produtos = {}
        for j, nome in prod_cols.items():
            dose = _to_num(row.iloc[j])
            if dose is not None and dose > 0:
                produtos[nome] = dose

        ha_area = _to_num(row.iloc[col_area]) if col_area is not None else None
        ha_aplicado = ha_area or 0.0
        if ha_aplicado <= 0 and not produtos:
            continue

        produto_resumo = ", ".join(f"{k} {v}" for k, v in sorted(produtos.items())) if produtos else None
        data_inicio = _to_date(row.iloc[col_data]) if col_data is not None else None
        periodo_mes = data_inicio.strftime("%Y-%m") if data_inicio else None

        reg = {
            "prestador": "ECOAERO",
            "operacao_realizada": "Controle de Lagartas / Micronutrientes",
            "produto": produto_resumo,
            "horto": "Taquarussu",
            "talhao_raw": talhao.upper(),
            "talhao_codigo": _talhao_codigo(talhao),
            "ha_total": ha_area,
            "ha_aplicado": ha_aplicado if ha_aplicado > 0 else ha_area,
            "data_inicio": data_inicio,
            "tarifa_rs_ha": None,
            "valor_total": None,
            "recomendacao": None,
            "volume_calda": _norm_txt(row.iloc[col_calda]) if col_calda is not None else None,
            "area_floresta_ha": ha_area,
            "produtos_por_ha": produtos or None,
            "observacao": None,
            "periodo_mes": periodo_mes,
            "periodo_ano": data_inicio.year if data_inicio else None,
            "periodo_mes_num": data_inicio.month if data_inicio else None,
            "arquivo_origem": path.name,
            "aba_origem": aba,
            "linha_origem": i + 1,
        }
        reg["hash_registro"] = _hash_registro(reg)
        registros.append(reg)

    return registros


def ler_arquivo_terceiros(caminho: str | Path) -> pd.DataFrame:
    path = Path(caminho)
    if not path.is_file():
        raise FileNotFoundError(path)

    prestador = _detectar_prestador(path)
    xls = pd.ExcelFile(path)
    todos: list[dict] = []

    for aba in xls.sheet_names:
        raw = pd.read_excel(path, sheet_name=aba, header=None)
        if prestador == "ECOAERO":
            todos.extend(_parse_ecoaero(raw, path, aba))
        else:
            todos.extend(_parse_coser_forion(raw, path, aba, prestador))

    if not todos:
        return pd.DataFrame(columns=SCHEMA_COLUNAS)

    df = pd.DataFrame(todos)
    df = df.drop_duplicates(subset=["hash_registro"], keep="first")
    return df[SCHEMA_COLUNAS]


def ler_pasta_terceiros(pasta: str | Path) -> pd.DataFrame:
    pasta = Path(pasta)
    partes = []
    for path in sorted(pasta.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        try:
            df = ler_arquivo_terceiros(path)
            if len(df):
                partes.append(df)
        except Exception as exc:
            raise RuntimeError(f"Erro ao ler {path}: {exc}") from exc

    if not partes:
        return pd.DataFrame(columns=SCHEMA_COLUNAS)

    df = pd.concat(partes, ignore_index=True)
    df = df.drop_duplicates(subset=["hash_registro"], keep="first")
    return df.reset_index(drop=True)


if __name__ == "__main__":
    import sys

    alvo = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    df = ler_pasta_terceiros(alvo) if Path(alvo).is_dir() else ler_arquivo_terceiros(alvo)
    print(f"{len(df)} registros")
    print(df.groupby("prestador").size())
    print(df.head(10).to_string())
