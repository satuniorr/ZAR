# -*- coding: utf-8 -*-
import os
import sqlite3
import pandas as pd
import hashlib
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
import numpy as np
import logging

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuração Inicial ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
BASE_DIR = '/home/ubuntu/zar_app'
DATABASE = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'xlsx'}
ADMIN_PASSWORD_HASH = hashlib.sha256('#compras321!'.encode()).hexdigest()
INITIAL_DATA_FILE = os.path.join(BASE_DIR, 'data.xlsx')

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Funções Auxiliares ---
def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_date(date_str):
    if isinstance(date_str, datetime):
        return date_str.strftime('%Y-%m-%d')
    if isinstance(date_str, str):
        try:
            dt_obj = pd.to_datetime(date_str, errors='coerce')
            if pd.notna(dt_obj):
                return dt_obj.strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Erro ao parsear data '{date_str}': {e}")
            return None
    return None

def clean_price(price_str):
    if price_str is None:
        return None
    try:
        # Correção: Remover pontos de milhar antes de substituir vírgula
        cleaned = re.sub(r'[R$\s]', '', str(price_str)).replace(".", "").replace(",", ".")
        if not cleaned:
            return None
        return float(cleaned)
    except (ValueError, TypeError) as e:
        logger.warning(f"Erro ao limpar preço '{price_str}': {e}")
        return None

def calculate_lead_time_compra(dt_pedido_str, dt_aprov_sol_str):
    dt_pedido = pd.to_datetime(dt_pedido_str, errors='coerce')
    dt_aprov_sol = pd.to_datetime(dt_aprov_sol_str, errors='coerce')
    if pd.isna(dt_pedido) or pd.isna(dt_aprov_sol):
        return None
    if dt_pedido >= dt_aprov_sol:
        return (dt_pedido - dt_aprov_sol).days
    else:
        return 'contrato'

def calculate_lead_time_entrega(dt_receb_str, dt_aprov_pedido_str):
    dt_receb = pd.to_datetime(dt_receb_str, errors='coerce')
    dt_aprov_pedido = pd.to_datetime(dt_aprov_pedido_str, errors='coerce')
    if pd.isna(dt_receb) or pd.isna(dt_aprov_pedido):
        return None
    if dt_receb >= dt_aprov_pedido:
        return (dt_receb - dt_aprov_pedido).days
    else:
        return None

def calculate_atraso_entrega(dt_receb_str, dt_entrega_orig_str):
    dt_receb = pd.to_datetime(dt_receb_str, errors='coerce')
    dt_entrega_orig = pd.to_datetime(dt_entrega_orig_str, errors='coerce')
    if pd.isna(dt_receb) or pd.isna(dt_entrega_orig):
        return None
    delta = (dt_receb - dt_entrega_orig).days
    return max(0, delta)

# --- Funções do Banco de Dados ---
def get_db():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Erro ao conectar ao banco de dados: {e}")
        return None

def init_db(force_create=False):
    conn = get_db()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        if force_create:
            cursor.execute("DROP TABLE IF EXISTS solicitacoes")
            logger.info("Tabela 'solicitacoes' existente removida (force_create=True).")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='solicitacoes'")
        table_exists = cursor.fetchone()
        if not table_exists:
            logger.info("Criando tabela 'solicitacoes'...")
            cursor.execute('''
                CREATE TABLE solicitacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    Solicitacao TEXT,
                    DtAbertura TEXT,
                    DtAprovSol TEXT,
                    Comprador TEXT,
                    Fornecedor TEXT,
                    Produto TEXT,
                    Qtde REAL,
                    PrecoUnitario REAL,
                    PrecoUnitarioOrig TEXT,
                    Moeda TEXT,
                    VlrTotal REAL,
                    DtAprovPedido TEXT,
                    DtPedido TEXT,
                    Pedido TEXT,
                    DtEntregaOrig TEXT,
                    DtEntregaAtual TEXT,
                    DtReceb TEXT,
                    Status TEXT,
                    Etapa TEXT,
                    DiasAtrSol INTEGER,
                    LeadTimeCompra TEXT,
                    LeadTimeEntrega INTEGER,
                    AtrasoEntrega INTEGER
                )
            ''')
            conn.commit()
            logger.info("Tabela 'solicitacoes' criada.")
        else:
            logger.info("Tabela 'solicitacoes' já existe.")
    except sqlite3.Error as e:
        logger.error(f"Erro durante init_db: {e}")
    finally:
        conn.close()

def process_and_load_excel(file_path):
    conn = None # Initialize conn to None
    try:
        df = pd.read_excel(file_path)
        logger.info(f"Colunas encontradas no Excel: {df.columns.tolist()}")

        # Renomear colunas para remover espaços e caracteres especiais
        df.columns = [re.sub(r'[.\s]+', '', col) for col in df.columns]
        logger.info(f"Colunas após renomear: {df.columns.tolist()}")

        # Verificar colunas essenciais após renomear
        expected_cols_renamed = [
            'Solicitação', 'DtAbertura', 'DtAprovSol', 'Comprador', 'Fornecedor',
            'Produto', 'Qtde', 'PreçoUnitário', 'Moeda', 'Vlrtotal',
            'DtAprovPedido', 'DtPedido', 'Pedido', 'DtEntregaOrig', 'DtEntregaAtual',
            'DtReceb', 'Status', 'Etapa', 'DiasAtrSol'
        ]
        missing_cols = [col for col in expected_cols_renamed if col not in df.columns]
        if missing_cols:
            logger.error(f"Erro: Colunas ausentes no arquivo Excel após renomear: {missing_cols}")
            return False, f"Colunas ausentes: {', '.join(missing_cols)}"

        conn = get_db()
        if not conn:
             return False, "Falha ao conectar ao banco de dados."
        cursor = conn.cursor()

        cursor.execute("DELETE FROM solicitacoes")
        logger.info("Dados antigos da tabela 'solicitacoes' removidos.")

        rows_processed = 0
        for index, row in df.iterrows():
            try:
                preco_unitario_orig = row.get('PreçoUnitário', None)
                preco_unitario = clean_price(preco_unitario_orig)
                vlr_total = clean_price(row.get('Vlrtotal'))

                status = str(row.get('Status', '')).strip().lower()
                if status == 'nao aprovado':
                    status = 'não aprovado'
                comprador = str(row.get('Comprador', '')).strip().title()
                if comprador not in ['Miriam', 'Irineu']:
                    comprador = 'Outro'

                lead_time_compra = calculate_lead_time_compra(row.get('DtPedido'), row.get('DtAprovSol'))
                lead_time_entrega = calculate_lead_time_entrega(row.get('DtReceb'), row.get('DtAprovPedido'))
                atraso_entrega = calculate_atraso_entrega(row.get('DtReceb'), row.get('DtEntregaOrig'))

                dias_atr_sol_raw = row.get('DiasAtrSol')
                dias_atr_sol = int(dias_atr_sol_raw) if pd.notna(dias_atr_sol_raw) and isinstance(dias_atr_sol_raw, (int, float)) else 0

                cursor.execute('''
                    INSERT INTO solicitacoes (
                        Solicitacao, DtAbertura, DtAprovSol, Comprador, Fornecedor, Produto, Qtde,
                        PrecoUnitario, PrecoUnitarioOrig, Moeda, VlrTotal, DtAprovPedido, DtPedido, Pedido,
                        DtEntregaOrig, DtEntregaAtual, DtReceb, Status, Etapa, DiasAtrSol,
                        LeadTimeCompra, LeadTimeEntrega, AtrasoEntrega
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(row.get('Solicitação', '')),
                    parse_date(row.get('DtAbertura')),
                    parse_date(row.get('DtAprovSol')),
                    comprador,
                    str(row.get('Fornecedor', '')),
                    str(row.get('Produto', '')),
                    row.get('Qtde'),
                    preco_unitario,
                    str(preco_unitario_orig) if preco_unitario_orig is not None else None,
                    str(row.get('Moeda', '')),
                    vlr_total,
                    parse_date(row.get('DtAprovPedido')),
                    parse_date(row.get('DtPedido')),
                    str(row.get('Pedido', '')),
                    parse_date(row.get('DtEntregaOrig')),
                    parse_date(row.get('DtEntregaAtual')),
                    parse_date(row.get('DtReceb')),
                    status,
                    str(row.get('Etapa', '')),
                    dias_atr_sol,
                    str(lead_time_compra) if lead_time_compra is not None else None,
                    lead_time_entrega,
                    atraso_entrega
                ))
                rows_processed += 1
            except Exception as row_error:
                 logger.error(f"Erro ao processar linha {index}: {row_error} - Dados: {row.to_dict()}")
                 # Optionally skip the row or handle differently
                 continue # Skip to next row

        conn.commit()
        logger.info(f"Dados do arquivo {os.path.basename(file_path)} carregados com sucesso. {rows_processed} linhas processadas.")
        return True, f"{rows_processed} registros carregados com sucesso."

    except FileNotFoundError:
        logger.error(f"Erro: Arquivo não encontrado em {file_path}")
        return False, "Arquivo Excel não encontrado."
    except Exception as e:
        logger.exception(f"Erro geral ao processar o arquivo Excel: {e}")
        if conn:
            try:
                conn.rollback()
            except sqlite3.Error as rb_err:
                 logger.error(f"Erro ao fazer rollback: {rb_err}")
        return False, f"Erro inesperado ao processar Excel: {e}"
    finally:
        if conn:
            conn.close()

# --- Funções para buscar dados do Dashboard ---
def get_dashboard_data():
    conn = get_db()
    if not conn:
        return {}
    cursor = conn.cursor()
    data = {}
    try:
        # Total de Solicitações
        cursor.execute("SELECT COUNT(*) FROM solicitacoes")
        data['total_solicitacoes'] = cursor.fetchone()[0]

        # Total Comprado (Aprovado)
        cursor.execute("SELECT SUM(VlrTotal) FROM solicitacoes WHERE Status = 'aprovado'")
        total_compras = cursor.fetchone()[0]
        data['total_compras'] = total_compras if total_compras else 0

        # Solicitações por Comprador (Miriam e Irineu, ordem decrescente)
        cursor.execute("SELECT Comprador, COUNT(*) as count FROM solicitacoes WHERE Comprador IN ('Miriam', 'Irineu') GROUP BY Comprador ORDER BY count DESC")
        data['por_comprador'] = {row['Comprador']: row['count'] for row in cursor.fetchall()}

        # Solicitações por Etapa
        cursor.execute("SELECT Etapa, COUNT(*) as count FROM solicitacoes GROUP BY Etapa ORDER BY Etapa")
        data['por_etapa'] = {row['Etapa']: row['count'] for row in cursor.fetchall()}

        # Solicitações Atrasadas (Cotar/Cotada)
        cursor.execute("SELECT Solicitacao, Etapa, Comprador, DiasAtrSol FROM solicitacoes WHERE Etapa IN ('02_COTAR', '05_COTADA') ORDER BY DiasAtrSol DESC")
        data['atrasadas_cotacao'] = [dict(row) for row in cursor.fetchall()]

        # Indicadores (Médias)
        cursor.execute("SELECT LeadTimeCompra, LeadTimeEntrega, AtrasoEntrega FROM solicitacoes")
        all_indicators = cursor.fetchall()

        lt_compra_days = [int(i['LeadTimeCompra']) for i in all_indicators if i['LeadTimeCompra'] and i['LeadTimeCompra'].isdigit()]
        lt_entrega_days = [i['LeadTimeEntrega'] for i in all_indicators if i['LeadTimeEntrega'] is not None]
        atraso_entrega_days = [i['AtrasoEntrega'] for i in all_indicators if i['AtrasoEntrega'] is not None]

        data['lead_time_compra_medio'] = round(np.mean(lt_compra_days), 2) if lt_compra_days else 'N/A'
        data['lead_time_entrega_medio'] = round(np.mean(lt_entrega_days), 2) if lt_entrega_days else 'N/A'
        data['atraso_entrega_medio'] = round(np.mean(atraso_entrega_days), 2) if atraso_entrega_days else 'N/A'

        # Desempenho por Comprador (Total Comprado, ordem decrescente)
        cursor.execute("SELECT Comprador, SUM(VlrTotal) as total FROM solicitacoes WHERE Status = 'aprovado' AND Comprador IN ('Miriam', 'Irineu') GROUP BY Comprador ORDER BY total DESC")
        data['desempenho_comprador'] = {row['Comprador']: row['total'] if row['total'] else 0 for row in cursor.fetchall()}

    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar dados do dashboard: {e}")
        # Retornar dados parciais ou vazios em caso de erro
        return data # Ou return {} para indicar falha completa
    finally:
        conn.close()
    return data

# --- Rota Principal (Chatbot) ---
@app.route('/')
def index():
    return render_template('index.html')

# --- Rotas da Área Administrativa ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin_dashboard'))
    error = None
    if request.method == 'POST':
        password = request.form['password']
        if hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['logged_in'] = True
            flash('Login bem-sucedido!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Senha incorreta!'
            flash(error, 'danger')
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nenhum arquivo selecionado', 'warning')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Nenhum arquivo selecionado', 'warning')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                file.save(filepath)
                flash(f'Arquivo {filename} enviado com sucesso!', 'info')
                success, message = process_and_load_excel(filepath)
                if success:
                    flash(f'Arquivo processado: {message}', 'success')
                else:
                    flash(f'Erro ao processar arquivo: {message}', 'danger')
            except Exception as e:
                logger.exception(f"Erro ao salvar/processar upload: {e}")
                flash(f'Erro crítico ao salvar ou processar o arquivo: {e}', 'danger')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Tipo de arquivo não permitido. Use .xlsx', 'danger')
            return redirect(request.url)

    # Buscar dados para o dashboard na requisição GET
    dashboard_data = get_dashboard_data()
    return render_template('admin.html', data=dashboard_data)

# --- API para Chatbot ---
@app.route('/api/chat', methods=['POST'])
def chat_api():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({'reply': 'Por favor, envie uma mensagem.'})

    logger.info(f"Mensagem recebida do chatbot: {user_message}")
    reply = "Desculpe, não consegui processar sua pergunta. Por favor, tente reformular ou entre em contato com os compradores Miriam ou Irineu."
    conn = get_db()
    if not conn:
         return jsonify({'reply': 'Erro ao conectar ao banco de dados. Tente novamente mais tarde.'})

    cursor = conn.cursor()
    try:
        # 1. Verificar status da solicitação X
        match_status = re.search(r'(?:status|estado)\s+(?:da\s+)?(?:solicitação|pedido)\s+(\w+)', user_message, re.IGNORECASE)
        if match_status:
            solicitacao_id = match_status.group(1)
            cursor.execute("SELECT Status, Etapa, Comprador FROM solicitacoes WHERE Solicitacao = ?", (solicitacao_id,))
            result = cursor.fetchone()
            if result:
                reply = f"Olá! A solicitação {solicitacao_id} está no status '{result['Status']}' e na etapa '{result['Etapa']}'. O comprador responsável é {result['Comprador']}."
            else:
                reply = f"Olá! Não encontrei a solicitação {solicitacao_id}. Poderia verificar o número? Se precisar de ajuda, fale com Miriam ou Irineu."

        # 2. Quantas solicitações estão pendentes?
        elif re.search(r'(?:quantas|numero de)\s+(?:solicitações|pedidos)\s+(?:estão|estao)\s+pendentes', user_message, re.IGNORECASE):
            # Definir o que é 'pendente' (ex: não 'aprovado' ou 'finalizado')
            cursor.execute("SELECT COUNT(*) FROM solicitacoes WHERE Status NOT IN ('aprovado', 'finalizado', 'cancelado')") # Ajuste os status conforme necessário
            count = cursor.fetchone()[0]
            reply = f"Atualmente, há {count} solicitações consideradas pendentes."

        # 3. Quais solicitações estão com mais de X dias de atraso?
        match_atraso = re.search(r'(?:quais|listar)\s+(?:solicitações|pedidos)\s+(?:com|com mais de|acima de)\s+(\d+)\s+dias\s+(?:de\s+)?(?:atraso|atrasadas)', user_message, re.IGNORECASE)
        if match_atraso:
            dias_atraso = int(match_atraso.group(1))
            cursor.execute("SELECT Solicitacao, Comprador, DiasAtrSol FROM solicitacoes WHERE DiasAtrSol > ? ORDER BY DiasAtrSol DESC", (dias_atraso,))
            results = cursor.fetchall()
            if results:
                reply = f"Encontrei {len(results)} solicitações com mais de {dias_atraso} dias de atraso:\n"
                reply += "\n".join([f"- Solicitação {r['Solicitacao']} ({r['Comprador']}): {r['DiasAtrSol']} dias" for r in results])
            else:
                reply = f"Ótimo! Não há solicitações com mais de {dias_atraso} dias de atraso no momento."

        # Adicionar mais padrões de perguntas aqui...

        else:
            reply = "Olá! 😊 Não entendi bem sua pergunta. Você pode tentar perguntar sobre:\n- O status de uma solicitação (ex: 'status da solicitação 12345')\n- Quantas solicitações estão pendentes\n- Quais solicitações estão atrasadas (ex: 'solicitações com mais de 7 dias de atraso')\nSe precisar de algo mais específico, por favor, fale com os super compradores Miriam ou Irineu!"

    except sqlite3.Error as e:
        logger.error(f"Erro ao consultar o banco de dados para o chatbot: {e}")
        reply = "Tive um problema ao buscar as informações no banco de dados. Por favor, tente novamente ou contate Miriam ou Irineu."
    except Exception as e:
        logger.exception(f"Erro inesperado na API do chatbot: {e}")
        reply = "Ocorreu um erro inesperado. Por favor, contate Miriam ou Irineu."
    finally:
        conn.close()

    return jsonify({'reply': reply})


# --- Inicialização ---
if __name__ == '__main__':
    init_db() # Garante que o DB e a tabela existam
    conn_check = get_db()
    if conn_check:
        cursor = conn_check.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM solicitacoes")
            count = cursor.fetchone()[0]
            if count == 0 and os.path.exists(INITIAL_DATA_FILE):
                logger.info("Banco de dados vazio. Carregando dados iniciais...")
                success, message = process_and_load_excel(INITIAL_DATA_FILE)
                if success:
                    logger.info(f"Dados iniciais carregados: {message}")
                else:
                    logger.error(f"Falha ao carregar dados iniciais: {message}")
            elif count > 0:
                logger.info(f"Banco de dados já contém {count} registros.")
        except sqlite3.Error as e:
            logger.error(f"Erro ao verificar contagem inicial ou carregar dados: {e}")
        finally:
            conn_check.close()
    else:
        logger.error("Não foi possível conectar ao banco de dados na inicialização.")

    logger.info("Iniciando servidor Flask em http://0.0.0.0:5000")
    # Usar Waitress para produção
    # from waitress import serve
    # serve(app, host='0.0.0.0', port=5000)
    app.run(host='0.0.0.0', port=5000)
