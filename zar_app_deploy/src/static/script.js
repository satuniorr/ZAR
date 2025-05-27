document.addEventListener('DOMContentLoaded', function() {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');

    // Função para adicionar mensagem ao chat
    function addMessage(message, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(isUser ? 'user-message' : 'bot-message');
        messageDiv.textContent = message;
        chatBox.appendChild(messageDiv);
        
        // Rolar para a mensagem mais recente
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Função para enviar mensagem para o backend
    async function sendMessage(message) {
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message }),
            });

            if (!response.ok) {
                throw new Error('Erro na comunicação com o servidor');
            }

            const data = await response.json();
            return data.reply;
        } catch (error) {
            console.error('Erro:', error);
            return 'Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde ou entre em contato com Miriam ou Irineu.';
        }
    }

    // Função para processar o envio de mensagem
    async function processUserMessage() {
        const message = userInput.value.trim();
        if (message === '') return;

        // Adicionar mensagem do usuário ao chat
        addMessage(message, true);
        userInput.value = '';

        // Mostrar indicador de digitação (opcional)
        const typingIndicator = document.createElement('div');
        typingIndicator.classList.add('message', 'bot-message', 'typing-indicator');
        typingIndicator.textContent = 'ZAR está digitando...';
        chatBox.appendChild(typingIndicator);
        chatBox.scrollTop = chatBox.scrollHeight;

        // Enviar mensagem para o backend e receber resposta
        const reply = await sendMessage(message);
        
        // Remover indicador de digitação
        chatBox.removeChild(typingIndicator);
        
        // Adicionar resposta do bot
        addMessage(reply);
    }

    // Event listeners
    sendButton.addEventListener('click', processUserMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            processUserMessage();
        }
    });

    // Foco inicial no campo de entrada
    userInput.focus();
});
