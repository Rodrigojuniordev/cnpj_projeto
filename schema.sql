CREATE DATABASE IF NOT EXISTS cnpj_db;
USE cnpj_db;

-- Tabelas principais
CREATE TABLE IF NOT EXISTS empresas (
    cnpj_basico CHAR(8) NOT NULL,
    razao_social VARCHAR(150),
    natureza_juridica INT,
    qualificacao_responsavel INT,
    capital_social DECIMAL(14,2),
    porte_empresa INT,
    ente_federativo_responsavel VARCHAR(100),
    PRIMARY KEY (cnpj_basico)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS estabelecimentos (
    cnpj_basico CHAR(8) NOT NULL,
    cnpj_ordem CHAR(4) NOT NULL,
    cnpj_dv CHAR(2) NOT NULL,
    identificador_matriz_filial INT,
    nome_fantasia VARCHAR(150),
    situacao_cadastral INT,
    data_situacao_cadastral DATE,
    motivo_situacao_cadastral INT,
    nome_cidade_exterior VARCHAR(100),
    pais INT,
    data_inicio_atividade DATE,
    cnae_fiscal_principal INT,
    cnae_fiscal_secundaria TEXT,
    tipo_logradouro VARCHAR(50),
    logradouro VARCHAR(150),
    numero VARCHAR(30),
    complemento VARCHAR(150),
    bairro VARCHAR(100),
    cep CHAR(8),
    uf CHAR(2),
    municipio INT,
    ddd1 VARCHAR(4),
    telefone1 VARCHAR(10),
    ddd2 VARCHAR(4),
    telefone2 VARCHAR(10),
    ddd_fax VARCHAR(4),
    fax VARCHAR(10),
    correio_eletronico VARCHAR(150),
    situacao_especial VARCHAR(100),
    data_situacao_especial DATE,
    PRIMARY KEY (cnpj_basico, cnpj_ordem, cnpj_dv)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS socios (
    cnpj_basico CHAR(8) NOT NULL,
    identificador_socio INT,
    nome_socio_razao_social VARCHAR(150),
    cpf_cnpj_socio VARCHAR(14) NOT NULL,
    qualificacao_socio INT NOT NULL,
    data_entrada_sociedade DATE,
    pais INT,
    representante_legal VARCHAR(11),
    nome_do_representante VARCHAR(150),
    qualificacao_representante_legal INT,
    faixa_etaria INT,
    PRIMARY KEY (cnpj_basico, cpf_cnpj_socio, qualificacao_socio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS simples (
    cnpj_basico CHAR(8) NOT NULL,
    opcao_simples CHAR(1),
    data_opcao_simples DATE,
    data_exclusao_simples DATE,
    opcao_mei CHAR(1),
    data_opcao_mei DATE,
    data_exclusao_mei DATE,
    PRIMARY KEY (cnpj_basico)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Staging (sem chave primaria, para carga rapida)
DROP TABLE IF EXISTS empresas_staging;
CREATE TABLE empresas_staging LIKE empresas;
ALTER TABLE empresas_staging DROP PRIMARY KEY;

DROP TABLE IF EXISTS estabelecimentos_staging;
CREATE TABLE estabelecimentos_staging LIKE estabelecimentos;
ALTER TABLE estabelecimentos_staging DROP PRIMARY KEY;

DROP TABLE IF EXISTS socios_staging;
CREATE TABLE socios_staging LIKE socios;
ALTER TABLE socios_staging DROP PRIMARY KEY;

DROP TABLE IF EXISTS simples_staging;
CREATE TABLE simples_staging LIKE simples;
ALTER TABLE simples_staging DROP PRIMARY KEY;

-- Auxiliares
CREATE TABLE IF NOT EXISTS cnaes (
    codigo VARCHAR(20) PRIMARY KEY,
    descricao VARCHAR(300)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS municipios (
    codigo INT PRIMARY KEY,
    nome VARCHAR(100),
    uf CHAR(2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS naturezas (
    codigo INT PRIMARY KEY,
    descricao VARCHAR(200)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS paises (
    codigo INT PRIMARY KEY,
    descricao VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS motivos (
    codigo INT PRIMARY KEY,
    descricao VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS qualificacoes (
    codigo INT PRIMARY KEY,
    descricao VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS portes (
    codigo INT PRIMARY KEY,
    descricao VARCHAR(50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO portes (codigo, descricao) VALUES
(0, 'NAO INFORMADO'),
(1, 'MICRO EMPRESA'),
(2, 'EMPRESA DE PEQUENO PORTE'),
(3, 'EMPRESA DE MEDIO PORTE'),
(4, 'GRANDE EMPRESA');