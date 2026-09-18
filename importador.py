# -*- coding: utf-8 -*-
from config import AUXILIARES, TABELAS


class Importador:
    """Faz o LOAD DATA nas tabelas e a consolidacao."""

    def __init__(self, banco):
        self.banco = banco

    # ---------------- Auxiliares ----------------

    def importar_auxiliar(self, arquivo, tipo):
        tabela, colunas = AUXILIARES[tipo]

        self.banco.executar("TRUNCATE TABLE " + tabela)

        arquivo = arquivo.replace("\\", "/")

        sql = f"""
            LOAD DATA LOCAL INFILE '{arquivo}'
            INTO TABLE {tabela}
            CHARACTER SET latin1
            FIELDS TERMINATED BY ';'
            ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            IGNORE 1 LINES
            ({colunas});
        """
        return self.banco.executar(sql)

    # ---------------- Principais ----------------

    def importar_principal(self, arquivo, tipo):
        arquivo = arquivo.replace("\\", "/")

        if tipo == "EMPRESA":
            return self._importar_empresa(arquivo)
        if tipo == "ESTABELE":
            return self._importar_estabelecimento(arquivo)
        if tipo == "SOCIO":
            return self._importar_socio(arquivo)
        if tipo == "SIMPLES":
            return self._importar_simples(arquivo)

        return False

    def _importar_empresa(self, arquivo):
        sql = f"""
            LOAD DATA LOCAL INFILE '{arquivo}'
            INTO TABLE empresas_staging
            CHARACTER SET latin1
            FIELDS TERMINATED BY ';'
            ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            (
                cnpj_basico,
                razao_social,
                natureza_juridica,
                qualificacao_responsavel,
                @capital,
                porte_empresa,
                ente_federativo_responsavel
            )
            SET capital_social = NULLIF(REPLACE(@capital, ',', '.'), '');
        """
        return self.banco.executar(sql)

    def _importar_socio(self, arquivo):
        sql = f"""
            LOAD DATA LOCAL INFILE '{arquivo}'
            INTO TABLE socios_staging
            CHARACTER SET latin1
            FIELDS TERMINATED BY ';'
            ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            (
                cnpj_basico,
                identificador_socio,
                nome_socio_razao_social,
                cpf_cnpj_socio,
                qualificacao_socio,
                @data,
                pais,
                representante_legal,
                nome_do_representante,
                qualificacao_representante_legal,
                faixa_etaria
            )
            SET data_entrada_sociedade =
                IF(
                    @data REGEXP '^[0-9]{{8}}$'
                    AND @data != '00000000',
                    STR_TO_DATE(@data, '%Y%m%d'),
                    NULL
                );
        """
        return self.banco.executar(sql)

    def _importar_estabelecimento(self, arquivo):
        sql = f"""
            LOAD DATA LOCAL INFILE '{arquivo}'
            INTO TABLE estabelecimentos_staging
            CHARACTER SET latin1
            FIELDS TERMINATED BY ';'
            ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            (
                cnpj_basico,
                cnpj_ordem,
                cnpj_dv,
                identificador_matriz_filial,
                nome_fantasia,
                situacao_cadastral,
                @data_sit,
                motivo_situacao_cadastral,
                nome_cidade_exterior,
                pais,
                @data_ini,
                cnae_fiscal_principal,
                cnae_fiscal_secundaria,
                tipo_logradouro,
                logradouro,
                numero,
                complemento,
                bairro,
                cep,
                uf,
                municipio,
                ddd1,
                telefone1,
                ddd2,
                telefone2,
                ddd_fax,
                fax,
                correio_eletronico,
                situacao_especial,
                @data_esp
            )
            SET
                data_situacao_cadastral =
                    IF(
                        @data_sit REGEXP '^[0-9]{{8}}$'
                        AND @data_sit != '00000000',
                        STR_TO_DATE(@data_sit, '%Y%m%d'),
                        NULL
                    ),
                data_inicio_atividade =
                    IF(
                        @data_ini REGEXP '^[0-9]{{8}}$'
                        AND @data_ini != '00000000',
                        STR_TO_DATE(@data_ini, '%Y%m%d'),
                        NULL
                    ),
                data_situacao_especial =
                    IF(
                        @data_esp REGEXP '^[0-9]{{8}}$'
                        AND @data_esp != '00000000',
                        STR_TO_DATE(@data_esp, '%Y%m%d'),
                        NULL
                    );
        """
        return self.banco.executar(sql)

    def _importar_simples(self, arquivo):
        sql = f"""
            LOAD DATA LOCAL INFILE '{arquivo}'
            INTO TABLE simples_staging
            CHARACTER SET latin1
            FIELDS TERMINATED BY ';'
            ENCLOSED BY '"'
            LINES TERMINATED BY '\\n'
            (
                cnpj_basico,
                opcao_simples,
                @data_op,
                @data_ex,
                opcao_mei,
                @data_mei,
                @data_ex_mei
            )
            SET
                data_opcao_simples =
                    IF(
                        @data_op REGEXP '^[0-9]{{8}}$'
                        AND @data_op != '00000000',
                        STR_TO_DATE(@data_op, '%Y%m%d'),
                        NULL
                    ),
                data_exclusao_simples =
                    IF(
                        @data_ex REGEXP '^[0-9]{{8}}$'
                        AND @data_ex != '00000000',
                        STR_TO_DATE(@data_ex, '%Y%m%d'),
                        NULL
                    ),
                data_opcao_mei =
                    IF(
                        @data_mei REGEXP '^[0-9]{{8}}$'
                        AND @data_mei != '00000000',
                        STR_TO_DATE(@data_mei, '%Y%m%d'),
                        NULL
                    ),
                data_exclusao_mei =
                    IF(
                        @data_ex_mei REGEXP '^[0-9]{{8}}$'
                        AND @data_ex_mei != '00000000',
                        STR_TO_DATE(@data_ex_mei, '%Y%m%d'),
                        NULL
                    );
        """
        return self.banco.executar(sql)

    # ---------------- Dispatch ----------------

    def importar(self, arquivo, tipo):
        if tipo in AUXILIARES:
            return self.importar_auxiliar(arquivo, tipo)
        return self.importar_principal(arquivo, tipo)

    # ---------------- Consolidacao ----------------

    def consolidar(self):
        print("\nConsolidando...")

        for tabela, colunas in TABELAS.items():
            updates = ", ".join(
                f"{col.strip()} = VALUES({col.strip()})"
                for col in colunas.split(",")
            )
            sql = f"""
                INSERT INTO {tabela}
                SELECT DISTINCT * FROM {tabela}_staging
                ON DUPLICATE KEY UPDATE {updates}
            """
            self.banco.executar(sql)

        print("Limpando staging...")
        self.banco.limpar_staging()
