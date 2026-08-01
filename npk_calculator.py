"""
Calculadora de NPK.

Extrai a formula (N-P-K) diretamente do nome do fertilizante, que na Santa
Vergínia ja vem no padrao "<marca> NN-NN-NN", ex:
    "Sulfammo 10-05-18" -> N=10, P2O5=05, K2O=18
    "Top-mix 14-14-10"  -> N=14, P2O5=14, K2O=10
    "Basifós 06-34-05"  -> N=06, P2O5=34, K2O=05
    "kcl 00-00-58"      -> N=00, P2O5=00, K2O=58

Se o nome nao tiver esse padrao, cai no cadastro manual FORMULAS_ADUBO como
fallback (util para fertilizantes foliares ou nomes fora do padrao).
"""
import re

import pandas as pd

RE_FORMULA = re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})\s*-\s*(\d{1,3})")

# Cadastro de apoio para fertilizantes cujo nome nao contem a formula
# (completar conforme novos insumos aparecerem nas planilhas)
FORMULAS_ADUBO = {
    "10-10-10": {"N": 10, "P": 10, "K": 10},
    "20-05-20": {"N": 20, "P": 5, "K": 20},
}


def extrair_formula(nome_fertilizante: str):
    """Retorna (N, P, K) em percentual a partir do nome do fertilizante, ou None se nao achar."""
    if not isinstance(nome_fertilizante, str):
        return None
    m = RE_FORMULA.search(nome_fertilizante)
    if m:
        return tuple(int(x) for x in m.groups())
    chave = nome_fertilizante.strip()
    if chave in FORMULAS_ADUBO:
        f = FORMULAS_ADUBO[chave]
        return (f["N"], f["P"], f["K"])
    return None


def calcular_npk_aplicado(kg_adubo: float, pct_n: float, pct_p: float, pct_k: float) -> dict:
    """
    kg de nutriente puro aplicado a partir do total de adubo e da formula do rotulo.
    Ex: 239 kg de adubo 14-14-10 -> 239/100 * 14 = 33.46 kg de N
    """
    if kg_adubo is None or pd.isna(kg_adubo):
        return {"N_kg": None, "P2O5_kg": None, "K2O_kg": None}
    fator = kg_adubo / 100
    return {
        "N_kg": round(fator * pct_n, 2),
        "P2O5_kg": round(fator * pct_p, 2),
        "K2O_kg": round(fator * pct_k, 2),
    }


def dose_por_ha(kg_adubo: float, area_ha: float, pct_n: float, pct_p: float, pct_k: float) -> dict:
    """Mesma logica, normalizada por hectare - permite comparar talhoes com formulas diferentes."""
    npk = calcular_npk_aplicado(kg_adubo, pct_n, pct_p, pct_k)
    if not area_ha or pd.isna(area_ha) or area_ha == 0:
        return {"N_kg_ha": None, "P2O5_kg_ha": None, "K2O_kg_ha": None}
    return {
        "N_kg_ha": round(npk["N_kg"] / area_ha, 2) if npk["N_kg"] is not None else None,
        "P2O5_kg_ha": round(npk["P2O5_kg"] / area_ha, 2) if npk["P2O5_kg"] is not None else None,
        "K2O_kg_ha": round(npk["K2O_kg"] / area_ha, 2) if npk["K2O_kg"] is not None else None,
    }


def aplicar_calculadora_no_df(
    df: pd.DataFrame,
    col_fertilizante: str,
    col_kg: str,
    col_area_ha: str,
) -> pd.DataFrame:
    """Aplica a calculadora de NPK em todas as linhas de um DataFrame de aplicacoes,
    adicionando as colunas: formula_npk, N_kg, P2O5_kg, K2O_kg, N_kg_ha, P2O5_kg_ha, K2O_kg_ha."""
    df = df.copy()
    formulas = df[col_fertilizante].apply(extrair_formula)

    df["formula_npk"] = formulas.apply(lambda f: f"{f[0]}-{f[1]}-{f[2]}" if f else "não identificada")

    npk_cols = df.apply(
        lambda row: calcular_npk_aplicado(row[col_kg], *extrair_formula(row[col_fertilizante]))
        if extrair_formula(row[col_fertilizante]) else {"N_kg": None, "P2O5_kg": None, "K2O_kg": None},
        axis=1, result_type="expand",
    )
    df = pd.concat([df, npk_cols], axis=1)

    dose_cols = df.apply(
        lambda row: dose_por_ha(row[col_kg], row[col_area_ha], *extrair_formula(row[col_fertilizante]))
        if extrair_formula(row[col_fertilizante]) else {"N_kg_ha": None, "P2O5_kg_ha": None, "K2O_kg_ha": None},
        axis=1, result_type="expand",
    )
    df = pd.concat([df, dose_cols], axis=1)

    return df


if __name__ == "__main__":
    # teste rapido com os fertilizantes reais observados nas planilhas
    for nome in ["Sulfammo 10-05-18", "Top-mix 14-14-10", "Basifós 06-34-05", "kcl 00-00-58", "Mosaic 06-34-10"]:
        formula = extrair_formula(nome)
        print(nome, "->", formula)

    print(calcular_npk_aplicado(239, 14, 14, 10))
    print(dose_por_ha(4000, 64.2, 10, 5, 18))
