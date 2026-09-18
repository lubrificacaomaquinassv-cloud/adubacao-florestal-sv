-- =============================================================================
-- Schema: operações florestais de terceiros (drone / pulverização)
-- Prestadores: COSER, F-ORION, ECOAERO
-- =============================================================================

CREATE TABLE IF NOT EXISTS operacoes_florestais_terceiros_drone (
    id                  BIGSERIAL PRIMARY KEY,
    prestador           TEXT NOT NULL CHECK (prestador IN ('COSER', 'F-ORION', 'ECOAERO')),
    operacao_realizada  TEXT,
    produto             TEXT,
    horto               TEXT,
    talhao_raw          TEXT NOT NULL,
    talhao_codigo       TEXT,
    ha_total            NUMERIC(12, 2),
    ha_aplicado         NUMERIC(12, 2) NOT NULL CHECK (ha_aplicado > 0),
    data_inicio         DATE,
    tarifa_rs_ha        NUMERIC(12, 2),
    valor_total         NUMERIC(14, 2),
    recomendacao        TEXT,
    volume_calda        TEXT,
    area_floresta_ha    NUMERIC(12, 2),
    produtos_por_ha     JSONB,
    observacao          TEXT,
    periodo_mes         TEXT,
    periodo_ano         INT,
    periodo_mes_num     INT,
    arquivo_origem      TEXT,
    aba_origem          TEXT,
    linha_origem        INT,
    hash_registro       TEXT NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_terceiros_drone_prestador
    ON operacoes_florestais_terceiros_drone (prestador);

CREATE INDEX IF NOT EXISTS idx_terceiros_drone_horto
    ON operacoes_florestais_terceiros_drone (horto);

CREATE INDEX IF NOT EXISTS idx_terceiros_drone_talhao
    ON operacoes_florestais_terceiros_drone (talhao_codigo);

CREATE INDEX IF NOT EXISTS idx_terceiros_drone_periodo
    ON operacoes_florestais_terceiros_drone (periodo_mes);

CREATE INDEX IF NOT EXISTS idx_terceiros_drone_data
    ON operacoes_florestais_terceiros_drone (data_inicio);

COMMENT ON TABLE operacoes_florestais_terceiros_drone IS
    'Operações florestais executadas por terceiros (COSER pulverização, F-ORION drone, EcoAero drone).';

COMMENT ON COLUMN operacoes_florestais_terceiros_drone.talhao_raw IS
    'Código original da planilha (ex: 392/393, 315 AB, 341 ao 343).';

COMMENT ON COLUMN operacoes_florestais_terceiros_drone.talhao_codigo IS
    'Primeiro número extraído do talhão para cruzamento com public.dim_talhoes.codigo (KML).';

COMMENT ON COLUMN operacoes_florestais_terceiros_drone.produtos_por_ha IS
    'EcoAero: doses por produto (JSON). Demais prestadores: NULL.';
