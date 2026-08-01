# Adubação Florestal SV

Painel de acompanhamento de adubação de cobertura e adubação de base
(subsolagem) na Fazenda Santa Vergínia, com mapa interativo geoespacial
e calculadora de NPK.

Repositório: `lubrificacaomaquinassv-cloud/adubacao-florestal-sv`

## O que o painel faz

1. Lê o mapa da fazenda (KML) e extrai os talhões (número, classe, área) da
   pasta **"Talhões (TIP / Silvipastoril / Silvicultura / Pastagem)"**.
2. Lê a planilha de **Adubação de Cobertura** (uma aba por retiro).
3. Lê a planilha de **Adubação de Base / Subsolagem** (bloco "Subsolado" +
   bloco "A subsolar" na mesma aba).
4. Calcula o NPK real aplicado (N, P₂O₅, K₂O em kg e kg/ha) extraindo a
   fórmula direto do nome do fertilizante (ex: "Sulfammo 10-05-18").
5. Cruza tudo com o cadastro geoespacial e mostra: mapa colorido por status
   de execução, KPIs, tabelas por retiro, e uma calculadora interativa.
6. Opcionalmente grava tudo no Supabase (schema em `sql/schema.sql`).

## Rodar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

Depois suba na barra lateral: o `.kml`, a planilha de Cobertura e a
planilha de Base/Subsolagem.

## Conectar ao Supabase (opcional)

1. No DBeaver, execute `sql/schema.sql` no seu projeto Supabase (habilita
   PostGIS e cria as tabelas `dim_talhao_florestal`,
   `fato_adubacao_cobertura`, `fato_adubacao_base`).
2. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`
   e preencha `SUPABASE_DB_URL` com a string de conexão do **Transaction
   Pooler** (porta 6543), no mesmo padrão dos outros sistemas (SIGCF,
   SIGPEC).
3. No Streamlit Cloud, configure o mesmo valor em **Settings → Secrets**.
4. Com isso, a aba "☁️ Supabase" do painel habilita o botão de gravação.

## Deploy no Streamlit Cloud

1. Suba este repositório em
   `github.com/lubrificacaomaquinassv-cloud/adubacao-florestal-sv`.
2. Em [share.streamlit.io](https://share.streamlit.io), aponte para
   `app.py` na branch principal.
3. Configure o Secret `SUPABASE_DB_URL` (passo acima) se for usar
   gravação no banco.

## Pontos de atenção nos dados (encontrados na validação)

- **43 códigos de talhão se repetem no KML.** Em 13 casos é duplicata real
  de digitalização (mesmo talhão, mesma classe, mesma área — o parser já
  remove automaticamente). Nos outros **30 casos, o mesmo número de talhão
  existe em classes diferentes** (ex: talhão "17" em Silvicultura *e* em
  Silvipastoril, com áreas diferentes). O painel avisa esses casos na aba
  Mapa — vale confirmar com o coordenador da floresta a qual classe cada
  lançamento das planilhas se refere, para joins 100% corretos.
- **2 talhões da planilha de Cobertura não têm correspondência no KML**
  atual: `201` e `270/271 FRANGE`. Podem ser talhão novo, erro de digitação,
  ou nomenclatura diferente (ex: talhão fracionado) — vale checar.
- **Retiro não vem no KML.** O painel infere o retiro automaticamente a
  partir do nome da aba (Cobertura) ou da coluna "Horto" (Base). Se algum
  talhão não aparecer em nenhuma das duas planilhas ainda, ele fica sem
  retiro atribuído até a primeira aplicação ser registrada.

## Próximos passos (fora do escopo desta versão)

- Módulo de custo (preço de insumo + hora-máquina/mão de obra por talhão) —
  intencionalmente deixado de fora agora; entra como nova aba consumindo as
  mesmas tabelas, sem alterar o que já está pronto.
- Cadastro oficial de retiro por talhão (hoje inferido das planilhas).
