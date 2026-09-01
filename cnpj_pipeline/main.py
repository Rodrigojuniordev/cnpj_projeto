# -*- coding: utf-8 -*-
import os
import zipfile
import requests
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine, text
import sys
import re
import time
from dotenv import load_dotenv
from pathlib import Path

# Carrega variáveis de ambiente
load_dotenv()

# ===== CONFIGURAÇÕES =====
PASTA_DOWNLOADS = "./downloads"
ANO_MES = os.getenv("ANO_MES", "2026-08")

DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "u62iqi4i")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_NAME = os.getenv("DB_NAME", "cnpj_db")

os.makedirs(PASTA_DOWNLOADS, exist_ok=True)

# Engine SQLAlchemy
engine = create_engine(
    "mysql+pymysql://{}:{}@{}:{}/{}?local_infile=1".format(
        DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME
    ),
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)

# ===== FUNÇÕES AUXILIARES =====

def executar_query(sql):
    """Executa uma query SQL"""
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
            headers={
                "Depth": "1",
                "Content-Type": "application/xml"
            },
            timeout=30
        )
        
        print("Status WebDAV: {}".format(response.status_code))
        
        if response.status_code not in [200, 207]:
            print("WebDAV retornou status inesperado: {}".format(response.status_code))
            return []
        
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            print("ERRO ao parsear XML: {}".format(e))
            print("Conteúdo recebido (primeiros 200 chars):")
            print(response.text[:200])
            return []
        
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
                print("  Encontrado: {}".format(os.path.basename(link)))
        
        print("\n✅ Total: {} arquivos .zip encontrados".format(len(links)))
        return links
        
    except Exception as e:
        print("ERRO no WebDAV: {}".format(str(e)))
        return []

def baixar_arquivo(url, pasta_destino):
    """Baixa um arquivo via WebDAV"""
    nome_arquivo = os.path.basename(url)
    if not nome_arquivo.endswith('.zip'):
        nome_arquivo = "temp_{}.zip".format(int(time.time()))
    
    caminho_zip = os.path.join(pasta_destino, nome_arquivo)
    
    if os.path.exists(caminho_zip):
        print("⏭️ Arquivo já baixado: {}".format(nome_arquivo))
        return caminho_zip
    
    print("⬇️ Baixando {}...".format(nome_arquivo))
    
    try:
        with requests.get(url, auth=("YggdBLfdninEJX9", ""), stream=True, timeout=120) as r:
            r.raise_for_status()
            
            total_size = int(r.headers.get('content-length', 0))
            block_size = 1024 * 1024  # 1MB
            
            with open(caminho_zip, 'wb') as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progresso = (downloaded / total_size) * 100
                            print("\r  Progresso: {:.1f}%".format(progresso), end='')
                print()
        
        return caminho_zip
    except Exception as e:
        print("ERRO ao baixar: {}".format(str(e)))
        return None

def extrair_zip(caminho_zip):
    """Extrai arquivo ZIP e retorna o caminho do arquivo de dados"""
    try:
        pasta_destino = os.path.dirname(caminho_zip)
        nome_sem_zip = os.path.splitext(os.path.basename(caminho_zip))[0]
        pasta_extraida = os.path.join(pasta_destino, nome_sem_zip)
        
        print("📦 Extraindo {}...".format(os.path.basename(caminho_zip)))
        
        with zipfile.ZipFile(caminho_zip, 'r') as zip_ref:
            arquivos = zip_ref.namelist()
            print("  Arquivos no ZIP: {}".format(arquivos))
            zip_ref.extractall(pasta_extraida)
        
        arquivo_encontrado = None
        for root, dirs, files in os.walk(pasta_extraida):
            for file in files:
                caminho_completo = os.path.join(root, file)
                if os.path.getsize(caminho_completo) > 0:
                    arquivo_encontrado = caminho_completo
                    print("  ✅ Arquivo encontrado: {}".format(file))
                    break
            if arquivo_encontrado:
                break
        
        if not arquivo_encontrado:
            print("  ❌ Nenhum arquivo encontrado")
            print("  Conteúdo da pasta: {}".format(os.listdir(pasta_extraida)))
            return None
        
        return arquivo_encontrado
        
    except Exception as e:
        print("ERRO ao extrair: {}".format(str(e)))
        return None

def processar_arquivo(caminho_arquivo, tipo):
    """Processa arquivo baseado no tipo"""
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
    
    print("📥 Importando {}...".format(tipo))
    return executar_query(query)

# ===== FUNÇÃO DE CONSOLIDAÇÃO COM LIMPEZA AUTOMÁTICA =====

def consolidar_dados():
    """Consolida dados das staging para as tabelas oficiais e limpa staging"""
    print("\n🔄 CONSOLIDANDO DADOS (IGNORANDO DUPLICATAS)...")
    
    print("  Sincronizando Empresas...")
    executar_query("""
    INSERT IGNORE INTO empresas
    SELECT DISTINCT stg.* FROM empresas_staging stg;
    """)
    
    print("  Sincronizando Estabelecimentos...")
    executar_query("""
    INSERT IGNORE INTO estabelecimentos
    SELECT DISTINCT stg.* FROM estabelecimentos_staging stg;
    """)
    
    print("  Sincronizando Sócios...")
    executar_query("""
    INSERT IGNORE INTO socios
    SELECT DISTINCT stg.* FROM socios_staging stg;
    """)
    
    print("  Sincronizando Simples...")
    executar_query("""
    INSERT IGNORE INTO simples
    SELECT DISTINCT stg.* FROM simples_staging stg;
    """)
    
    # ===== LIMPEZA AUTOMÁTICA DAS STAGING =====
    print("\n🧹 Limpando tabelas staging...")
    executar_query("TRUNCATE TABLE empresas_staging;")
    executar_query("TRUNCATE TABLE estabelecimentos_staging;")
    executar_query("TRUNCATE TABLE socios_staging;")
    executar_query("TRUNCATE TABLE simples_staging;")
    print("✅ Staging limpas com sucesso!")

def main():
    """Função principal"""
    print("=" * 60)
    print("🚀 IMPORTACAO DADOS RECEITA FEDERAL - {}".format(ANO_MES))
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
    
    # Limpa staging
    print("\n🧹 Limpando tabelas de staging...")
    for tabela in ['empresas_staging', 'estabelecimentos_staging', 'socios_staging', 'simples_staging']:
        executar_query("TRUNCATE TABLE {};".format(tabela))
    
    # Processa cada arquivo
    arquivos_processados = 0
    for url in links:
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
        
        caminho_zip = baixar_arquivo(url, PASTA_DOWNLOADS)
        if not caminho_zip:
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
    
    # Consolida e limpa staging automaticamente
    consolidar_dados()
    
    executar_query("SET foreign_key_checks = 1;")
    executar_query("SET unique_checks = 1;")
    
    print("\n" + "=" * 60)
    print("✅ IMPORTACAO CONCLUIDA COM SUCESSO!")
    print("📊 Arquivos processados: {}".format(arquivos_processados))
    print("=" * 60)

if __name__ == "__main__":
    main()
