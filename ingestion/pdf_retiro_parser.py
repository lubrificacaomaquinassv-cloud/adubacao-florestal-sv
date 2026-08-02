"""
Parser dos PDFs de "mapa por retiro" (ex: EUCALIPTO (2020), POCO AZUL (2020)).

Cada PDF e o mapa de UM retiro, com um circulo numerado por talhao (ex: 257,
89A, 173B) mais a area e o codigo de solo ao lado. O nome do retiro esta no
titulo do PDF (e tambem no nome do arquivo).

Esta funcao NAO tenta reconstruir area/codigo de solo por talhao (isso exige
clusterizar palavras por posicao x/y com mais precisao) - o objetivo aqui e
resolver o de-para talhao -> retiro, que e o dado que falta hoje para atribuir
retiro a todos os talhoes do mapa (hoje so os talhoes que ja aparecem nas
planilhas de adubacao tem retiro atribuido).
"""
import re
from pathlib import Path

import pandas as pd
import pdfplumber

# Nomes de retiro sao normalmente derivados do titulo dentro do PDF (mais
# confiavel que o nome do arquivo, que tem underscore/numero de talhao).
RE_TALHAO = re.compile(r"^\d{1,4}[A-Za-z]{0,2}$")

# tokens que aparecem no mapa mas NAO sao talhao (rotulos de mapa, legendas)
PALAVRAS_IGNORAR = {
    "APP", "CONDUÇÃO", "CONDUCAO", "Reservatório", "Reservatorio",
    "Bomba", "D'água", "D'agua", "Há", "Ha", "ha",
}


def _desduplicar_texto_bold(token: str) -> str:
    """
    Alguns desses PDFs simulam negrito duplicando cada caractere
    (ex: '243' vira '224433', 'Reservatório' vira 'RReesseerrvvaattóórriioo').
    Se o token tem esse padrao (cada caractere repetido em par), colapsa
    de volta para o texto original.
    """
    if len(token) % 2 != 0 or len(token) < 2:
        return token
    pares_iguais = all(token[i] == token[i + 1] for i in range(0, len(token), 2))
    return token[::2] if pares_iguais else token


def _corrigir_numeral_romano(nome_retiro: str) -> str:
    """str.title() transforma 'ALDEIA II' em 'Aldeia Ii'. Devolve o numeral
    romano para maiusculo (II, III, IV...) quando aplicavel."""
    def _fix(palavra):
        if re.fullmatch(r"[IVXivx]+", palavra) and palavra.upper() in {
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"
        }:
            return palavra.upper()
        return palavra
    return " ".join(_fix(p) for p in nome_retiro.split())


# Palavras de titulo (nome do retiro + ano) ficam sempre no topo da pagina;
# qualquer coisa acima dessa linha e cabecalho, nao talhao.
TOPO_CABECALHO_PT = 100


def _retiro_a_partir_do_titulo(caminho_pdf: str, texto_pagina: str) -> str:
    """Tenta achar o titulo tipo 'EUCALIPTO (2020)' no texto da pagina;
    se nao achar, deriva do nome do arquivo."""
    m = re.search(r"([A-ZÀ-Ú][A-ZÀ-Ú \d]+)\s*\((\d{4})\)", texto_pagina)
    if m:
        return _corrigir_numeral_romano(m.group(1).strip().title())

    nome = Path(caminho_pdf).stem
    nome = re.sub(r"^\d{4}_", "", nome)          # remove ano do inicio
    nome = re.sub(r"__.*$", "", nome)             # remove faixa de talhao no final (__464-481_)
    nome = nome.replace("_", " ").strip()
    return _corrigir_numeral_romano(nome.title())


def ler_talhoes_pdf_retiro(caminho_pdf: str) -> pd.DataFrame:
    """Le um PDF de mapa por retiro e retorna DataFrame [talhao, retiro, arquivo_origem]."""
    with pdfplumber.open(caminho_pdf) as pdf:
        talhoes_encontrados = set()
        texto_completo = ""

        for pagina in pdf.pages:
            texto_completo += (pagina.extract_text() or "") + "\n"
            for palavra in pagina.extract_words():
                if palavra["top"] < TOPO_CABECALHO_PT:
                    continue  # linha do titulo (nome do retiro + ano), nao e talhao
                token = _desduplicar_texto_bold(palavra["text"].strip())
                if token in PALAVRAS_IGNORAR:
                    continue
                if RE_TALHAO.match(token):
                    talhoes_encontrados.add(token.upper())

        retiro = _retiro_a_partir_do_titulo(caminho_pdf, texto_completo)

    return pd.DataFrame({
        "talhao": sorted(talhoes_encontrados),
        "retiro": retiro,
        "arquivo_origem": Path(caminho_pdf).name,
    })


def ler_pasta_pdfs_retiro(pasta: str) -> pd.DataFrame:
    """Le todos os .pdf de uma pasta e concatena o de-para talhao -> retiro.

    Se o mesmo talhao aparecer em mais de um PDF (ex: reprocessado em anos
    diferentes), mantem a primeira ocorrencia e reporta o conflito via
    a coluna 'duplicado'.
    """
    pasta_path = Path(pasta)
    arquivos = sorted(pasta_path.glob("*.pdf"))
    if not arquivos:
        return pd.DataFrame(columns=["talhao", "retiro", "arquivo_origem"])

    partes = [ler_talhoes_pdf_retiro(str(a)) for a in arquivos]
    df = pd.concat(partes, ignore_index=True)

    df["duplicado"] = df.duplicated(subset="talhao", keep=False)
    df_final = df.drop_duplicates(subset="talhao", keep="first").drop(columns="duplicado")

    return df_final


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        df = ler_pasta_pdfs_retiro(sys.argv[1])
        print(f"Total de talhoes mapeados: {len(df)}")
        print(df["retiro"].value_counts())
        print(df.head(20))
    else:
        for caminho in sys.argv[1:]:
            df = ler_talhoes_pdf_retiro(caminho)
            print(f"\n=== {caminho} ===")
            print(f"Retiro detectado: {df['retiro'].iloc[0] if len(df) else '?'}")
            print(f"Talhoes encontrados ({len(df)}): {df['talhao'].tolist()}")
