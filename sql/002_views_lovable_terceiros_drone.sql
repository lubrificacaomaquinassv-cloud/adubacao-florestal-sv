-- =============================================================================
-- Views Lovable — Operações florestais terceiros / drone
-- Consumo: painel gerencial, mapa GIS, dashboards por prestador/horto/talhão
-- =============================================================================

-- 1) Base enriquecida (talhão + período)
CREATE OR REPLACE VIEW vw_terceiros_drone_base AS
SELECT
    o.id,
    o.prestador,
    o.operacao_realizada,
    o.produto,
    o.horto,
    o.talhao_raw,
    o.talhao_codigo,
    o.ha_total,
    o.ha_aplicado,
    o.data_inicio,
    o.tarifa_rs_ha,
    o.valor_total,
    o.recomendacao,
    o.volume_calda,
    o.area_floresta_ha,
    o.produtos_por_ha,
    o.observacao,
    o.periodo_mes,
    o.periodo_ano,
    o.periodo_mes_num,
    to_char(o.data_inicio, 'YYYY-MM') AS mes_aplicacao,
    o.arquivo_origem,
    o.hash_registro,
    o.created_at
FROM operacoes_florestais_terceiros_drone o;


-- 2) Resumo por prestador e mês
CREATE OR REPLACE VIEW vw_terceiros_drone_resumo_prestador AS
SELECT
    prestador,
    coalesce(periodo_mes, mes_aplicacao, 'SEM_PERIODO') AS periodo_mes,
    count(*)::int                                           AS qtd_lancamentos,
    count(distinct talhao_raw)::int                         AS qtd_talhoes,
    count(distinct horto)::int                              AS qtd_hortos,
    round(sum(ha_aplicado)::numeric, 2)                     AS ha_aplicado_total,
    round(sum(coalesce(valor_total, 0))::numeric, 2)      AS valor_total_rs,
    round(avg(tarifa_rs_ha)::numeric, 2)                    AS tarifa_media_rs_ha
FROM vw_terceiros_drone_base
GROUP BY prestador, coalesce(periodo_mes, mes_aplicacao, 'SEM_PERIODO');


-- 3) Resumo por horto
CREATE OR REPLACE VIEW vw_terceiros_drone_por_horto AS
SELECT
    coalesce(horto, 'SEM_HORTO')                            AS horto,
    prestador,
    count(*)::int                                           AS qtd_lancamentos,
    count(distinct talhao_raw)::int                         AS qtd_talhoes,
    round(sum(ha_aplicado)::numeric, 2)                     AS ha_aplicado_total,
    round(sum(coalesce(valor_total, 0))::numeric, 2)      AS valor_total_rs
FROM vw_terceiros_drone_base
GROUP BY coalesce(horto, 'SEM_HORTO'), prestador;


-- 4) Agregado por talhão (para mapa / cruzamento KML)
CREATE OR REPLACE VIEW vw_terceiros_drone_por_talhao AS
SELECT
    talhao_codigo,
    max(talhao_raw)                                         AS talhao_raw_exemplo,
    max(horto)                                              AS horto_principal,
    count(*)::int                                           AS qtd_operacoes,
    count(distinct prestador)::int                          AS qtd_prestadores,
    string_agg(distinct prestador, ', ' ORDER BY prestador) AS prestadores,
    string_agg(distinct operacao_realizada, ' | '
        ORDER BY operacao_realizada)                        AS operacoes,
    round(sum(ha_aplicado)::numeric, 2)                     AS ha_aplicado_total,
    round(sum(coalesce(valor_total, 0))::numeric, 2)      AS valor_total_rs,
    min(data_inicio)                                        AS primeira_aplicacao,
    max(data_inicio)                                        AS ultima_aplicacao
FROM vw_terceiros_drone_base
WHERE talhao_codigo IS NOT NULL AND trim(talhao_codigo) <> ''
GROUP BY talhao_codigo;


-- 5) Detalhe por operação e produto (COSER / F-ORION)
CREATE OR REPLACE VIEW vw_terceiros_drone_por_operacao AS
SELECT
    prestador,
    coalesce(operacao_realizada, 'SEM_OPERACAO')            AS operacao_realizada,
    coalesce(produto, 'SEM_PRODUTO')                        AS produto,
    count(*)::int                                           AS qtd_lancamentos,
    round(sum(ha_aplicado)::numeric, 2)                     AS ha_aplicado_total,
    round(sum(coalesce(valor_total, 0))::numeric, 2)      AS valor_total_rs,
    round(avg(tarifa_rs_ha)::numeric, 2)                    AS tarifa_media_rs_ha
FROM vw_terceiros_drone_base
GROUP BY prestador, coalesce(operacao_realizada, 'SEM_OPERACAO'), coalesce(produto, 'SEM_PRODUTO');


-- 6) Mapa: join com dim_talhoes (KML já carregado via apontamento_campo)
-- Pré-requisito: public.dim_talhoes com codigo + area_ha (script carregar_talhoes_kml.py)
CREATE OR REPLACE VIEW vw_terceiros_drone_mapa AS
SELECT
    t.talhao_codigo,
    t.talhao_raw_exemplo,
    t.horto_principal,
    t.qtd_operacoes,
    t.prestadores,
    t.operacoes,
    t.ha_aplicado_total,
    t.valor_total_rs,
    t.primeira_aplicacao,
    t.ultima_aplicacao,
    d.id                                                    AS talhao_id,
    d.nome                                                  AS talhao_nome,
    d.classe_uso                                            AS classe,
    l.nome                                                  AS retiro,
    d.area_ha                                               AS area_ha_kml,
    CASE
        WHEN d.codigo IS NULL THEN 'SEM_POLIGONO_KML'
        WHEN t.ha_aplicado_total >= coalesce(d.area_ha, 0) * 0.99 THEN 'COMPLETO'
        WHEN t.ha_aplicado_total > 0 THEN 'PARCIAL'
        ELSE 'NAO_INICIADO'
    END AS status_cobertura_terceiros
FROM vw_terceiros_drone_por_talhao t
LEFT JOIN public.dim_talhoes d
    ON upper(trim(d.codigo)) = upper(trim(t.talhao_codigo))
   AND coalesce(d.ativo, true)
LEFT JOIN public.dim_locais l
    ON l.id = d.id_local;


-- 7) API flat para Lovable (JSON-friendly, uma linha por lançamento + FK dim_talhoes)
CREATE OR REPLACE VIEW vw_api_terceiros_drone AS
SELECT
    b.id,
    b.prestador,
    b.operacao_realizada,
    b.produto,
    b.horto,
    b.talhao_raw,
    b.talhao_codigo,
    d.id                                                    AS talhao_id,
    d.nome                                                  AS talhao_nome,
    d.classe_uso,
    l.nome                                                  AS retiro,
    d.area_ha                                               AS area_cadastro_ha,
    b.ha_total,
    b.ha_aplicado,
    b.data_inicio,
    b.tarifa_rs_ha,
    b.valor_total,
    b.periodo_mes,
    b.mes_aplicacao,
    b.produtos_por_ha,
    b.arquivo_origem,
    b.hash_registro
FROM vw_terceiros_drone_base b
LEFT JOIN public.dim_talhoes d
    ON upper(trim(d.codigo)) = upper(trim(b.talhao_codigo))
   AND coalesce(d.ativo, true)
LEFT JOIN public.dim_locais l
    ON l.id = d.id_local
ORDER BY b.data_inicio DESC NULLS LAST, b.id DESC;

COMMENT ON VIEW vw_api_terceiros_drone IS
    'Endpoint Lovable: listagem flat de operações terceiros/drone.';
