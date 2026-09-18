# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

# Pastas
DOWNLOADS = "./downloads"
STATE = "./state"

# Competencia: se vazio, detecta automaticamente
COMPETENCIA = os.getenv("COMPETENCIA") or None

# Banco
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "cnpj_db")

# Receita
TOKEN = os.getenv("TOKEN_RECEITA")
URL_BASE = "https://arquivos.receitafederal.gov.br"
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 1800))
CHUNK = 1024 * 1024

# Validacao basica
if not TOKEN:
    raise SystemExit("Erro: TOKEN_RECEITA nao definido no .env")

if not DB_PASS:
    raise SystemExit("Erro: DB_PASS nao definido no .env")

# Mapeamento de arquivos auxiliares
AUXILIARES = {
    "CNAES": ("cnaes", "codigo, descricao"),
    "MUNICIPIOS": ("municipios", "codigo, nome, uf"),
    "NATUREZAS": ("naturezas", "codigo, descricao"),
    "PAISES": ("paises", "codigo, descricao"),
    "MOTIVOS": ("motivos", "codigo, descricao"),
    "QUALIFICACOES": ("qualificacoes", "codigo, descricao"),
}

# Colunas que devem ser atualizadas na consolidacao (ON DUPLICATE KEY)
TABELAS = {
    "empresas":
        "razao_social, natureza_juridica, qualificacao_responsavel, "
        "capital_social, porte_empresa, ente_federativo_responsavel",

    "estabelecimentos":
        "identificador_matriz_filial, nome_fantasia, situacao_cadastral, "
        "data_situacao_cadastral, motivo_situacao_cadastral, "
        "nome_cidade_exterior, pais, data_inicio_atividade, "
        "cnae_fiscal_principal, cnae_fiscal_secundaria, tipo_logradouro, "
        "logradouro, numero, complemento, bairro, cep, uf, municipio, "
        "ddd1, telefone1, ddd2, telefone2, ddd_fax, fax, "
        "correio_eletronico, situacao_especial, data_situacao_especial",

    "socios":
        "identificador_socio, nome_socio_razao_social, "
        "data_entrada_sociedade, pais, representante_legal, "
        "nome_do_representante, qualificacao_representante_legal, "
        "faixa_etaria",

    "simples":
        "opcao_simples, data_opcao_simples, data_exclusao_simples, "
        "opcao_mei, data_opcao_mei, data_exclusao_mei",
}

# Tipos principais que passam por staging
PRINCIPAIS = ["EMPRESA", "ESTABELE", "SOCIO", "SIMPLES"]
