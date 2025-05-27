document.addEventListener('DOMContentLoaded', function() {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');

    // Função para adicionar mensagem ao chat
    function addMessage(message, isUser = false, isTyping = false) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        if (isTyping) {
            messageDiv.classList.add('bot-message', 'typing-indicator');
            messageDiv.innerHTML = `<span></span><span></span><span></span>`; // Simple dot animation
        } else {
            messageDiv.classList.add(isUser ? 'user-message' : 'bot-message');
            // Sanitize message slightly to prevent basic HTML injection if needed
            // For simple text, textContent is safer
            messageDiv.textContent = message;
        }
        chatBox.appendChild(messageDiv);

        // Rolar para a mensagem mais recente
        chatBox.scrollTop = chatBox.scrollHeight;
        return messageDiv; // Return the element if needed (e.g., for removal)
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
                // Try to get error message from response body if available
                let errorMsg = 'Erro na comunicação com o servidor.';
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.reply || errorMsg;
                } catch (e) { /* Ignore if response is not JSON */ }
                throw new Error(errorMsg);
            }

            const data = await response.json();
            return data.reply;
        } catch (error) {
            console.error('Erro:', error);
            // Return the specific error message or a generic one
            return error.message || 'Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde ou entre em contato com Miriam ou Irineu.';
        }
    }

    // Função para processar o envio de mensagem
    async function processUserMessage() {
        const message = userInput.value.trim();
        if (message === '') return;

        // Disable input and button
        userInput.disabled = true;
        sendButton.disabled = true;
        sendButton.textContent = 'Enviando...'; // Indicate activity

        // Adicionar mensagem do usuário ao chat
        addMessage(message, true);
        userInput.value = '';

        // Mostrar indicador de digitação
        const typingIndicatorElement = addMessage('', false, true);

        // Enviar mensagem para o backend e receber resposta
        const reply = await sendMessage(message);

        // Remover indicador de digitação
        chatBox.removeChild(typingIndicatorElement);

        // Adicionar resposta do bot
        addMessage(reply);

        // Re-enable input and button
        userInput.disabled = false;
        sendButton.disabled = false;
        sendButton.textContent = 'Enviar';
        userInput.focus(); // Return focus to input
    }

    // Event listeners
    sendButton.addEventListener('click', processUserMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !userInput.disabled) { // Prevent sending while disabled
            processUserMessage();
        }
    });

    // Foco inicial no campo de entrada
    userInput.focus();
});

