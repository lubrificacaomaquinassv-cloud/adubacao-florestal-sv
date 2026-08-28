"""
Acorda apps do Streamlit Cloud que estejam hibernados.

Diferente de um simples curl/GET, este script abre cada app num navegador
headless (Playwright), espera a página carregar e, se encontrar o botão
"Yes, get this app back up!" (tela de hibernação do Streamlit), clica nele
e aguarda o app efetivamente subir.
"""

import sys
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

APPS = [
    "https://adubacao-florestal-sv-hbqqrye72rwfhhcjprayxy.streamlit.app/",
    "https://combustivelcontrole-anzrygxbtddxvaemy9nkru.streamlit.app/",
    "https://controlerefeitoriosv-th2xfqra7fgc9ygar4horq.streamlit.app/",
    "https://controle-viagens-sv-3trphy8ylik6fzpvgiminb.streamlit.app/",
    "https://gestor-oficina-sv-arib89adkrv4nrypidqhzr.streamlit.app/",
    "https://oficina-veiculos-sv-adwnggsbrx87kswdesytxm.streamlit.app/",
    "https://oficinasv-dytza2mqqtujkytuj7jgfm.streamlit.app/",
    "https://painel-estrategico-sv-aeeenn9xq3hvcnahvf7i3u.streamlit.app/",
    "https://painel-viagens-sv-dffyeuecgd2aknozaqmevy.streamlit.app/",
    "https://postosv-uezgfprqxwbclszt8dwrue.streamlit.app/",
    "https://requisicao-compras.streamlit.app/",
    "https://sigalmox-hketsapjanxcwfzbjscrxa.streamlit.app/",
    "https://sigalmox-acayytyrats59qfmtbe36u.streamlit.app/",
    "https://sigcf-borracharia-3gmjvre7rhltewlpenfzrv.streamlit.app/",
    "https://sigcf-financeiro-rzmgqrrw56zfzkn4sfjng7.streamlit.app/",
    "https://sigcf-plataforma-2s7iitujusrbtzde49xdel.streamlit.app/",
    "https://sigcf-rh-kjc7swamm7cicncjrtzfvo.streamlit.app/",
    "https://sigcf-rh-nvkpmzcrbbrfrsjznrxnmo.streamlit.app/",
    "https://sigpec-ex2z9ndnksuyrwkhphtzd5.streamlit.app/",
]

# Textos que aparecem no botão de reativação em diferentes variações
WAKE_BUTTON_SELECTORS = [
    "text=Yes, get this app back up!",
    "button:has-text('get this app back up')",
    "text=Yes, get this app back up",
]

TIMEOUT_MS = 30_000  # 30s por app pra carregar/reagir


def wake_app(page, url: str) -> str:
    """Retorna um status curto: 'ok_direto', 'acordado', 'falhou'."""
    try:
        page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
    except PWTimeout:
        return "falhou (timeout ao abrir)"

    # Dá um tempo pra Streamlit renderizar a tela de hibernação (se houver)
    page.wait_for_timeout(3000)

    clicked = False
    for selector in WAKE_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                btn.click(timeout=5000)
                clicked = True
                break
        except PWTimeout:
            continue
        except Exception:
            continue

    if not clicked:
        # Não achou botão de hibernação -> app já estava ativo
        return "ok_direto (já estava acordado)"

    # Espera o app efetivamente subir após o clique.
    # O Streamlit troca a tela de hibernação pelo app real; aguardamos
    # o seletor padrão de app carregado ou um tempo generoso de boot.
    try:
        page.wait_for_selector("text=Yes, get this app back up!", state="detached", timeout=60_000)
    except PWTimeout:
        pass  # segue mesmo assim; deu tempo suficiente na maioria dos casos

    page.wait_for_timeout(5000)
    return "acordado (clicou e aguardou boot)"


def main():
    falhas = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for url in APPS:
            print(f"\n>>> Verificando: {url}")
            try:
                status = wake_app(page, url)
                print(f"    Status: {status}")
                if status.startswith("falhou"):
                    falhas.append(url)
            except Exception as e:
                print(f"    ERRO inesperado: {e}")
                falhas.append(url)
            time.sleep(1)

        browser.close()

    print("\n" + "=" * 50)
    if falhas:
        print(f"Concluído com {len(falhas)} falha(s):")
        for f in falhas:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("Todos os apps verificados/acordados com sucesso.")


if __name__ == "__main__":
    main()
