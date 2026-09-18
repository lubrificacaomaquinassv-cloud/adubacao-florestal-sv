"""
Validação dos registros de operações florestais de terceiros (drone/pulverização).
"""
from __future__ import annotations

import pandas as pd

REGRAS_OBRIGATORIAS = {
    "prestador": "Prestador ausente",
    "talhao_raw": "Talhão ausente",
    "ha_aplicado": "Área aplicada (ha) ausente ou inválida",
}

REGRAS_PRESTADOR = {
    "COSER": ["operacao_realizada", "produto", "horto", "ha_aplicado", "tarifa_rs_ha", "valor_total"],
    "F-ORION": ["operacao_realizada", "produto", "horto", "ha_aplicado"],
    "ECOAERO": ["talhao_raw", "ha_aplicado"],
}


def validar_operacoes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retorna DataFrame de alertas: colunas [hash_registro, severidade, campo, mensagem, ...registro].
    severidade: ERRO | AVISO | INFO
    """
    if df.empty:
        return pd.DataFrame(columns=["hash_registro", "severidade", "campo", "mensagem"])

    alertas: list[dict] = []

    for _, row in df.iterrows():
        base = {
            "hash_registro": row.get("hash_registro"),
            "prestador": row.get("prestador"),
            "talhao_raw": row.get("talhao_raw"),
            "arquivo_origem": row.get("arquivo_origem"),
            "linha_origem": row.get("linha_origem"),
        }

        for campo, msg in REGRAS_OBRIGATORIAS.items():
            val = row.get(campo)
            if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
                alertas.append({**base, "severidade": "ERRO", "campo": campo, "mensagem": msg})

        ha = row.get("ha_aplicado")
        if ha is not None and not pd.isna(ha) and float(ha) <= 0:
            alertas.append({**base, "severidade": "ERRO", "campo": "ha_aplicado", "mensagem": "ha_aplicado deve ser > 0"})

        prestador = row.get("prestador")
        for campo in REGRAS_PRESTADOR.get(prestador, []):
            val = row.get(campo)
            if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
                alertas.append({
                    **base,
                    "severidade": "AVISO",
                    "campo": campo,
                    "mensagem": f"Campo recomendado ausente para {prestador}: {campo}",
                })

        if row.get("valor_total") and row.get("tarifa_rs_ha") and row.get("ha_aplicado"):
            esperado = round(float(row["tarifa_rs_ha"]) * float(row["ha_aplicado"]), 2)
            real = round(float(row["valor_total"]), 2)
            if abs(esperado - real) > max(1.0, esperado * 0.05):
                alertas.append({
                    **base,
                    "severidade": "AVISO",
                    "campo": "valor_total",
                    "mensagem": f"Valor total ({real}) difere de tarifa×ha ({esperado})",
                })

        if not row.get("talhao_codigo"):
            alertas.append({
                **base,
                "severidade": "AVISO",
                "campo": "talhao_codigo",
                "mensagem": f"Talhão '{row.get('talhao_raw')}' sem código numérico para cruzamento KML",
            })

        if row.get("data_inicio") is None and prestador in ("COSER", "F-ORION"):
            alertas.append({
                **base,
                "severidade": "INFO",
                "campo": "data_inicio",
                "mensagem": "Data de início não informada",
            })

    return pd.DataFrame(alertas)


def resumo_validacao(df: pd.DataFrame, alertas: pd.DataFrame) -> dict:
    hashes_erro = set()
    if len(alertas):
        hashes_erro = set(alertas.loc[alertas["severidade"] == "ERRO", "hash_registro"].dropna())

    return {
        "total_registros": len(df),
        "registros_validos": len(df) - len(hashes_erro),
        "registros_com_erro": len(hashes_erro),
        "total_alertas": len(alertas),
        "alertas_erro": int((alertas["severidade"] == "ERRO").sum()) if len(alertas) else 0,
        "alertas_aviso": int((alertas["severidade"] == "AVISO").sum()) if len(alertas) else 0,
        "alertas_info": int((alertas["severidade"] == "INFO").sum()) if len(alertas) else 0,
        "por_prestador": df.groupby("prestador").size().to_dict() if len(df) else {},
        "ha_aplicado_total": round(float(df["ha_aplicado"].sum()), 2) if len(df) else 0,
        "valor_total_rs": round(float(df["valor_total"].fillna(0).sum()), 2) if len(df) else 0,
    }
