# -*- coding: utf-8 -*-
import os
import zipfile
import requests
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine, text
import sys
import re
import time
import hashlib
import json
from dotenv import load_dotenv
from pathlib import Path

# Carrega variáveis de ambiente
load_dotenv()

# ===== CONFIGURAÇÕES =====
PASTA_DOWNLOADS = "./downloads"
PASTA_STATE = "./state"
ANO_MES = os.getenv("COMPETENCIA", "2026-08")

DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "u62iqi4i")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "cnpj_db")

os.makedirs(PASTA_DOWNLOADS, exist_ok=True)
os.makedirs(PASTA_STATE, exist_ok=True)

# Engine SQLAlchemy
engine = create_engine(
    "mysql+pymysql://{}:{}@{}:{}/{}?local_infile=1".format(
        DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME
    ),
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)

# ===== FUNÇÕES DE HASH =====

def calcular_md5(caminho_arquivo):
    """Calcula o MD5 de um arquivo"""
    hash_md5 = hashlib.md5()
    try:
        with open(caminho_arquivo, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print("ERRO ao calcular MD5: {}".format(str(e)))
        return None

def carregar_hashes():
    """Carrega os hashes salvos do mês anterior"""
    arquivo_hash = os.path.join(PASTA_STATE, "hashes_{}.json".format(ANO_MES))
    if os.path.exists(arquivo_hash):
        try:
            with open(arquivo_hash, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def salvar_hashes(hashes):
    """Salva os hashes do mês atual"""
    arquivo_hash = os.path.join(PASTA_STATE, "hashes_{}.json".format(ANO_MES))
    with open(arquivo_hash, 'w') as f:
        json.dump(hashes, f, indent=4)
    print("✅ Hashes salvos em: {}".format(arquivo_hash))

# ===== FUNÇÕES PRINCIPAIS =====

def executar_query(sql):
    try:
        with engine.begin() as conexao:
            conexao.execute(text(sql))
        return True
    except Exception as e:
        print("ERRO: {}".format(str(e)))
        return False

def obter_links_zip():
    """Obtém links dos arquivos ZIP via WebDAV"""
    url = "https://arquivos.receitafederal.gov.br/public.php/webdav/{}".format(ANO_MES)
    print("Acessando WebDAV: {}".format(url))
    
    try:
        response = requests.request(
            "PROPFIND",
            url,
            auth=("YggdBLfdninEJX9", ""),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=30
        )
        
        if response.status_code not in [200, 207]:
            return []
        
        root = ET.fromstring(response.content)
        ns = {'d': 'DAV:'}
        links = []
        
        for href in root.findall('.//d:href', ns):
            caminho = href.text
            if caminho and caminho.lower().endswith('.zip'):
                if not caminho.startswith('http'):
                    link = "https://arquivos.receitafederal.gov.br{}".format(caminho)
                else:
                    link = caminho
                links.append(link)
        
        print("✅ Total: {} arquivos .zip encontrados".format(len(links)))
        return links
        
    except Exception as e:
        print("ERRO no WebDAV: {}".format(str(e)))
        return []

def baixar_arquivo(url, pasta_destino):
    """Baixa um arquivo via WebDAV e retorna o caminho e hash"""
    nome_arquivo = os.path.basename(url)
    caminho_zip = os.path.join(pasta_destino, nome_arquivo)
    
    # Verifica se já existe e calcula hash
    if os.path.exists(caminho_zip):
        hash_existente = calcular_md5(caminho_zip)
        if hash_existente:
            print("⏭️ Arquivo já existe: {} (MD5: {})".format(nome_arquivo, hash_existente[:8] + "..."))
            return caminho_zip, hash_existente
    
    print("⬇️ Baixando {}...".format(nome_arquivo))
    
    try:
        with requests.get(url, auth=("YggdBLfdninEJX9", ""), stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(caminho_zip, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
        
        # Calcula hash do arquivo baixado
        hash_arquivo = calcular_md5(caminho_zip)
        print("  ✅ Download concluído (MD5: {})".format(hash_arquivo[:8] + "..."))
        return caminho_zip, hash_arquivo
        
    except Exception as e:
        print("ERRO ao baixar: {}".format(str(e)))
        return None, None

def extrair_zip(caminho_zip):
    try:
        pasta_destino = os.path.dirname(caminho_zip)
        nome_sem_zip = os.path.splitext(os.path.basename(caminho_zip))[0]
        pasta_extraida = os.path.join(pasta_destino, nome_sem_zip)
        
        with zipfile.ZipFile(caminho_zip, 'r') as zip_ref:
            zip_ref.extractall(pasta_extraida)
        
        for root, dirs, files in os.walk(pasta_extraida):
            for file in files:
                caminho_completo = os.path.join(root, file)
                if os.path.getsize(caminho_completo) > 0:
                    return caminho_completo
        
        return None
    except Exception as e:
        print("ERRO ao extrair: {}".format(str(e)))
        return None

def processar_arquivo(caminho_arquivo, tipo):
    if not caminho_arquivo or not os.path.exists(caminho_arquivo):
        return False
    
    caminho_sql = caminho_arquivo.replace('\\', '/')
    
    try:
        with open(caminho_arquivo, 'r', encoding='latin1') as f:
            primeira_linha = f.readline()
            if 'CNPJ' in primeira_linha.upper() or 'SOCIO' in primeira_linha.upper():
                IGNORE_HEADER = "IGNORE 1 LINES"
            else:
                IGNORE_HEADER = ""
    except:
        IGNORE_HEADER = ""
    
    if tipo == "EMPRESA":
        query = """
        LOAD DATA LOCAL INFILE '{}'
        INTO TABLE empresas_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {}
        (cnpj_basico, razao_social, natureza_juridica, qualificacao_responsavel, @cap_social, porte_empresa, ente_federativo_responsavel)
        SET capital_social = NULLIF(REPLACE(@cap_social, ',', '.'), '');
        """.format(caminho_sql, IGNORE_HEADER)
    elif tipo == "ESTABELE":
        query = """
        LOAD DATA LOCAL INFILE '{}'
        INTO TABLE estabelecimentos_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {}
        (cnpj_basico, cnpj_ordem, cnpj_dv, identificador_matriz_filial, nome_fantasia, 
         situacao_cadastral, @data_sit, motivo_situacao_cadastral, nome_cidade_exterior, 
         pais, @data_ini, cnae_fiscal_principal, cnae_fiscal_secundaria, tipo_logradouro, 
         logradouro, numero, complemento, bairro, cep, uf, municipio, ddd1, telefone1, 
         ddd2, telefone2, ddd_fax, fax, correio_eletronico, situacao_especial, @data_esp)
        SET 
         data_situacao_cadastral = IF(@data_sit REGEXP '^[0-9]{{8}}$' AND @data_sit != '00000000', STR_TO_DATE(@data_sit, '%%Y%%m%%d'), NULL),
         data_inicio_atividade   = IF(@data_ini REGEXP '^[0-9]{{8}}$' AND @data_ini != '00000000', STR_TO_DATE(@data_ini, '%%Y%%m%%d'), NULL),
         data_situacao_especial  = IF(@data_esp REGEXP '^[0-9]{{8}}$' AND @data_esp != '00000000', STR_TO_DATE(@data_esp, '%%Y%%m%%d'), NULL);
        """.format(caminho_sql, IGNORE_HEADER)
    elif tipo == "SOCIO":
        query = """
        LOAD DATA LOCAL INFILE '{}'
        INTO TABLE socios_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {}
        (cnpj_basico, identificador_socio, nome_socio_razao_social, cpf_cnpj_socio, qualificacao_socio, @data_ent, pais, representante_legal, nome_do_representante, qualificacao_representante_legal, faixa_etaria)
        SET data_entrada_sociedade = IF(@data_ent REGEXP '^[0-9]{{8}}$' AND @data_ent != '00000000', STR_TO_DATE(@data_ent, '%%Y%%m%%d'), NULL);
        """.format(caminho_sql, IGNORE_HEADER)
    elif tipo == "SIMPLES":
        query = """
        LOAD DATA LOCAL INFILE '{}'
        INTO TABLE simples_staging
        CHARACTER SET latin1
        FIELDS TERMINATED BY ';' ENCLOSED BY '"' LINES TERMINATED BY '\\n'
        {}
        (cnpj_basico, opcao_simples, @data_op_simples, @data_ex_simples, opcao_mei, @data_op_mei, @data_ex_mei)
        SET 
         data_opcao_simples    = IF(@data_op_simples REGEXP '^[0-9]{{8}}$' AND @data_op_simples != '00000000', STR_TO_DATE(@data_op_simples, '%%Y%%m%%d'), NULL),
         data_exclusao_simples = IF(@data_ex_simples REGEXP '^[0-9]{{8}}$' AND @data_ex_simples != '00000000', STR_TO_DATE(@data_ex_simples, '%%Y%%m%%d'), NULL),
         data_opcao_mei        = IF(@data_op_mei REGEXP '^[0-9]{{8}}$' AND @data_op_mei != '00000000', STR_TO_DATE(@data_op_mei, '%%Y%%m%%d'), NULL),
         data_exclusao_mei     = IF(@data_ex_mei REGEXP '^[0-9]{{8}}$' AND @data_ex_mei != '00000000', STR_TO_DATE(@data_ex_mei, '%%Y%%m%%d'), NULL);
        """.format(caminho_sql, IGNORE_HEADER)
    else:
        return False
    
    return executar_query(query)

def consolidar_dados():
    """Consolida dados das staging para as tabelas oficiais (INCREMENTAL)"""
    print("\n🔄 CONSOLIDANDO DADOS (INCREMENTAL)...")
    
    print("  Sincronizando Empresas...")
    executar_query("""
    INSERT INTO empresas
    SELECT DISTINCT stg.* FROM empresas_staging stg
    ON DUPLICATE KEY UPDATE 
        razao_social = VALUES(razao_social),
        natureza_juridica = VALUES(natureza_juridica),
        qualificacao_responsavel = VALUES(qualificacao_responsavel),
        capital_social = VALUES(capital_social),
        porte_empresa = VALUES(porte_empresa),
        ente_federativo_responsavel = VALUES(ente_federativo_responsavel);
    """)
    
    print("  Sincronizando Estabelecimentos...")
    executar_query("""
    INSERT INTO estabelecimentos
    SELECT DISTINCT stg.* FROM estabelecimentos_staging stg
    ON DUPLICATE KEY UPDATE 
        identificador_matriz_filial = VALUES(identificador_matriz_filial),
        nome_fantasia = VALUES(nome_fantasia),
        situacao_cadastral = VALUES(situacao_cadastral),
        data_situacao_cadastral = VALUES(data_situacao_cadastral),
        motivo_situacao_cadastral = VALUES(motivo_situacao_cadastral),
        nome_cidade_exterior = VALUES(nome_cidade_exterior),
        pais = VALUES(pais),
        data_inicio_atividade = VALUES(data_inicio_atividade),
        cnae_fiscal_principal = VALUES(cnae_fiscal_principal),
        cnae_fiscal_secundaria = VALUES(cnae_fiscal_secundaria),
        tipo_logradouro = VALUES(tipo_logradouro),
        logradouro = VALUES(logradouro),
        numero = VALUES(numero),
        complemento = VALUES(complemento),
        bairro = VALUES(bairro),
        cep = VALUES(cep),
        uf = VALUES(uf),
        municipio = VALUES(municipio),
        ddd1 = VALUES(ddd1),
        telefone1 = VALUES(telefone1),
        ddd2 = VALUES(ddd2),
        telefone2 = VALUES(telefone2),
        ddd_fax = VALUES(ddd_fax),
        fax = VALUES(fax),
        correio_eletronico = VALUES(correio_eletronico),
        situacao_especial = VALUES(situacao_especial),
        data_situacao_especial = VALUES(data_situacao_especial);
    """)
    
    print("  Sincronizando Sócios...")
    executar_query("""
    INSERT INTO socios
    SELECT DISTINCT stg.* FROM socios_staging stg
    ON DUPLICATE KEY UPDATE 
        identificador_socio = VALUES(identificador_socio),
        nome_socio_razao_social = VALUES(nome_socio_razao_social),
        data_entrada_sociedade = VALUES(data_entrada_sociedade),
        pais = VALUES(pais),
        representante_legal = VALUES(representante_legal),
        nome_do_representante = VALUES(nome_do_representante),
        qualificacao_representante_legal = VALUES(qualificacao_representante_legal),
        faixa_etaria = VALUES(faixa_etaria);
    """)
    
    print("  Sincronizando Simples...")
    executar_query("""
    INSERT INTO simples
    SELECT DISTINCT stg.* FROM simples_staging stg
    ON DUPLICATE KEY UPDATE 
        opcao_simples = VALUES(opcao_simples),
        data_opcao_simples = VALUES(data_opcao_simples),
        data_exclusao_simples = VALUES(data_exclusao_simples),
        opcao_mei = VALUES(opcao_mei),
        data_opcao_mei = VALUES(data_opcao_mei),
        data_exclusao_mei = VALUES(data_exclusao_mei);
    """)
    
    print("\n🧹 Limpando tabelas staging...")
    executar_query("TRUNCATE TABLE empresas_staging;")
    executar_query("TRUNCATE TABLE estabelecimentos_staging;")
    executar_query("TRUNCATE TABLE socios_staging;")
    executar_query("TRUNCATE TABLE simples_staging;")
    print("✅ Staging limpas com sucesso!")

def main():
    print("=" * 60)
    print("🚀 IMPORTACAO INCREMENTAL - {}".format(ANO_MES))
    print("=" * 60)
    
    # Verifica MySQL
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ MySQL CONECTADO")
    except Exception as e:
        print("❌ ERRO MySQL: {}".format(str(e)))
        return
    
    # Configura sessão
    executar_query("SET SESSION sql_mode = '';")
    executar_query("SET SESSION unique_checks = 0;")
    executar_query("SET SESSION foreign_key_checks = 0;")
    
    # Obtém lista de arquivos
    print("\n📋 Obtendo lista de arquivos...")
    links = obter_links_zip()
    
    if not links:
        print("❌ Nenhum arquivo encontrado no diretório /{}".format(ANO_MES))
        return
    
    # Carrega hashes anteriores
    hashes_anteriores = carregar_hashes()
    hashes_atuais = {}
    arquivos_para_processar = []
    
    print("\n🔍 Verificando hashes dos arquivos...")
    
    for url in links:
        nome_arquivo = os.path.basename(url)
        
        # Baixa o arquivo e calcula hash
        caminho_zip, hash_atual = baixar_arquivo(url, PASTA_DOWNLOADS)
        if not caminho_zip:
            continue
        
        hashes_atuais[nome_arquivo] = hash_atual
        
        # Verifica se o hash mudou em relação ao mês anterior
        if nome_arquivo in hashes_anteriores:
            hash_anterior = hashes_anteriores[nome_arquivo]
            if hash_anterior == hash_atual:
                print("  ⏭️ {}: hash igual ao mês anterior - ignorando".format(nome_arquivo))
                continue
            else:
                print("  🔄 {}: hash DIFERENTE - processando".format(nome_arquivo))
        else:
            print("  🆕 {}: arquivo novo - processando".format(nome_arquivo))
        
        arquivos_para_processar.append(url)
    
    # Salva os hashes atuais para o próximo mês
    salvar_hashes(hashes_atuais)
    
    if not arquivos_para_processar:
        print("\n✅ Nenhum arquivo novo para processar.")
        return
    
    # Limpa staging
    print("\n🧹 Limpando tabelas de staging...")
    for tabela in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query("TRUNCATE TABLE {};".format(tabela))
    
    # Processa apenas arquivos com hash diferente
    arquivos_processados = 0
    for url in arquivos_para_processar:
        nome_arquivo = url.upper()
        
        tipo = None
        if "EMPRESA" in nome_arquivo:
            tipo = "EMPRESA"
        elif "ESTABELE" in nome_arquivo:
            tipo = "ESTABELE"
        elif "SOCIO" in nome_arquivo:
            tipo = "SOCIO"
        elif "SIMPLES" in nome_arquivo:
            tipo = "SIMPLES"
        else:
            print("⏭️ Ignorando arquivo auxiliar: {}".format(os.path.basename(url)))
            continue
        
        print("\n📥 Processando {}...".format(tipo))
        
        caminho_zip = os.path.join(PASTA_DOWNLOADS, os.path.basename(url))
        if not os.path.exists(caminho_zip):
            print("  ❌ Arquivo não encontrado: {}".format(caminho_zip))
            continue
        
        caminho_txt = extrair_zip(caminho_zip)
        if not caminho_txt:
            continue
        
        if processar_arquivo(caminho_txt, tipo):
            arquivos_processados += 1
        
        # Remove o zip após processar
        try:
            os.remove(caminho_zip)
            print("🗑️ ZIP removido: {}".format(os.path.basename(caminho_zip)))
        except Exception as e:
            print("⚠️ Não foi possível remover {}: {}".format(os.path.basename(caminho_zip), e))
    
    if arquivos_processados == 0:
        print("\n❌ Nenhum arquivo foi processado!")
        return
    
    # Consolida incremental
    consolidar_dados()
    
    executar_query("SET foreign_key_checks = 1;")
    executar_query("SET unique_checks = 1;")
    
    print("\n" + "=" * 60)
    print("✅ IMPORTACAO INCREMENTAL CONCLUIDA!")
    print("📊 Arquivos processados: {}".format(arquivos_processados))
    print("=" * 60)

if __name__ == "__main__":
    main()
