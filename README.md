# Instruções de Implantação - Chatbot ZAR

## Visão Geral

Este pacote contém o código-fonte completo para o Chatbot ZAR e seu painel administrativo. A aplicação foi desenvolvida em Python usando o framework Flask e utiliza Pandas/Numpy para processamento de dados, o que requer um ambiente de hospedagem compatível com essas bibliotecas.

## Estrutura do Projeto

```
/zar_app_deploy
|-- src/                 # Código fonte principal da aplicação Flask
|   |-- static/          # Arquivos estáticos (CSS, JS, Imagens)
|   |-- templates/       # Templates HTML (Jinja2)
|   |-- uploads/         # Pasta para uploads de planilhas (será criada se não existir)
|   |-- data.xlsx        # Planilha de exemplo inicial (com colunas incorretas, como discutido)
|   |-- database.db      # Banco de dados SQLite (será criado vazio na primeira execução)
|   `-- main.py          # Arquivo principal da aplicação Flask
|-- requirements.txt     # Lista de dependências Python
`-- venv/                # Ambiente virtual Python (recomendado recriar)
```

**Observação:** O arquivo `database.db` pode não estar presente ou estar vazio. Ele será criado automaticamente na primeira vez que a aplicação rodar. A pasta `uploads` também será criada automaticamente.

## Pré-requisitos

*   Python 3.11 ou superior
*   pip (gerenciador de pacotes Python)
*   Acesso a um terminal ou linha de comando

## Configuração Local (Para Testes)

1.  **Descompacte o arquivo ZIP:** Extraia o conteúdo do arquivo `zar_chatbot_package.zip` para uma pasta no seu computador.
2.  **Navegue até a pasta:** Abra o terminal e use o comando `cd` para entrar na pasta `zar_app_deploy` que você acabou de extrair.
3.  **Crie um Ambiente Virtual:**
    ```bash
    python3.11 -m venv venv
    ```
4.  **Ative o Ambiente Virtual:**
    *   No Linux/macOS:
        ```bash
        source venv/bin/activate
        ```
    *   No Windows:
        ```cmd
        venv\Scripts\activate
        ```
5.  **Instale as Dependências:**
    ```bash
    pip install -r requirements.txt
    ```
6.  **Execute a Aplicação:**
    ```bash
    python src/main.py
    ```
7.  **Acesse:** Abra seu navegador e acesse `http://127.0.0.1:5000`.
    *   A interface do chatbot estará na página inicial.
    *   O painel administrativo estará em `http://127.0.0.1:5000/login` (senha: `#compras321!`).

## Implantação (Deploy) em Produção

Devido ao uso de `numpy` e `pandas`, a implantação requer uma plataforma que suporte a instalação de pacotes Python com código nativo/compilado. Plataformas "Serverless" puras podem não funcionar diretamente.

**Plataformas Recomendadas:**

*   **Railway:** Oferece um bom suporte para aplicações Python e geralmente lida bem com dependências nativas.
*   **Render (com Docker):** Você pode criar um `Dockerfile` para definir o ambiente exato, incluindo a instalação de dependências do sistema se necessário, e então fazer o deploy da imagem Docker.
*   **Heroku (Pode exigir buildpacks específicos):** Similar ao Railway, mas pode precisar de configuração adicional para dependências nativas.
*   **Servidor VPS (AWS EC2, Google Cloud Compute Engine, DigitalOcean Droplet):** Oferece controle total sobre o ambiente, permitindo instalar qualquer dependência.

**Passos Gerais para Deploy (Exemplo com Gunicorn):**

1.  **Prepare o Comando de Inicialização:** A maioria das plataformas pedirá um comando para iniciar sua aplicação web. Use `gunicorn` para produção:
    ```bash
    gunicorn --chdir src main:app -w 4 -b 0.0.0.0:$PORT
    ```
    *   `-w 4`: Número de workers (ajuste conforme a plataforma/plano).
    *   `$PORT`: A plataforma geralmente define a porta através de uma variável de ambiente.
    *   `--chdir src`: Indica que o Gunicorn deve rodar a partir do diretório `src`.
2.  **Crie um `Procfile` (se necessário):** Algumas plataformas (como Heroku, Railway) usam um arquivo `Procfile` na raiz do projeto (`zar_app_deploy/Procfile`) para definir o comando web:
    ```Procfile
    web: gunicorn --chdir src main:app -w 4
    ```
    (A porta é geralmente gerenciada pela plataforma).
3.  **Configure a Plataforma:** Siga as instruções da plataforma escolhida para:
    *   Conectar seu repositório Git ou fazer upload do código.
    *   Definir o comando de build (geralmente `pip install -r requirements.txt`).
    *   Definir o comando de start (usando Gunicorn, como acima).
    *   Configurar variáveis de ambiente (se houver alguma - neste projeto, não há necessidade imediata).
4.  **Banco de Dados:** O SQLite (`database.db`) pode funcionar em algumas plataformas para aplicações simples, mas pode ter limitações (especialmente em ambientes sem disco persistente ou com múltiplos workers). Para maior robustez, considere migrar para PostgreSQL ou MySQL, o que exigiria alterações no código (`main.py`) e configuração na plataforma de hospedagem.

## Formato da Planilha Excel

Para que o upload e processamento funcionem corretamente na área administrativa, a planilha `.xlsx` deve conter **exatamente** as seguintes colunas (os nomes são importantes):

*   `Solicitação`
*   `DtAbertura`
*   `DtAprovSol`
*   `Comprador`
*   `Fornecedor`
*   `Produto`
*   `Qtde`
*   `Preço Unitário` (Formatado como número ou texto reconhecível, ex: "R$ 1.234,56" ou "1234.56")
*   `Moeda`
*   `Vlr total` (Formatado como número ou texto reconhecível)
*   `DtAprovPedido`
*   `DtPedido`
*   `Pedido`
*   `Dt.EntregaOrig`
*   `Dt.EntregaAtual`
*   `Dt.Receb`
*   `Status` (Ex: "aprovado", "não aprovado", "pendente")
*   `Etapa` (Ex: "01_SOLICITADA", "02_COTAR")
*   `Dias Atr Sol` (Número inteiro de dias)

Qualquer desvio nesses nomes ou a falta de alguma coluna pode causar erros no processamento.

---

Se tiver dúvidas durante a implantação, consulte a documentação da plataforma escolhida ou procure ajuda na comunidade específica da plataforma.
