import { useState } from 'react';
import { Send, Loader2, Bot, User } from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

/**
 * Chat page — natural language interface to enterprise APIs.
 *
 * TODO(#30): Connect to backend SSE streaming endpoint POST /api/v1/copilot/ask.
 * TODO(#31): Implement conversation persistence and loading.
 * TODO(#32): Add syntax highlighting for curl/code blocks in responses.
 * TODO(#33): Add typing indicator during agent execution.
 */
export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content:
        "Hello! I'm **Enterprise API Copilot**. I can help you discover, test, and execute enterprise APIs using natural language.\n\nTry asking:\n- *\"List all available payment APIs\"*\n- *\"Create a sandbox payment of ₹500\"*\n- *\"Show me the authentication flow for the Orders API\"*",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    // TODO(#30): Replace with real API call
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content:
            '🚧 **Agent execution is not yet implemented.**\n\nThis feature is coming in Phase 2. The backend and agent infrastructure are being built.\n\nCheck the [roadmap](https://github.com/your-org/enterprise-api-copilot) for progress.',
          timestamp: new Date(),
        },
      ]);
      setIsLoading(false);
    }, 1200);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] max-w-4xl mx-auto">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-white">Chat</h1>
        <p className="text-gray-400 text-sm mt-1">
          Interact with enterprise APIs using natural language.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
          >
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                message.role === 'assistant'
                  ? 'bg-brand-600'
                  : 'bg-gray-700'
              }`}
            >
              {message.role === 'assistant' ? (
                <Bot className="w-4 h-4 text-white" />
              ) : (
                <User className="w-4 h-4 text-gray-300" />
              )}
            </div>
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm ${
                message.role === 'assistant'
                  ? 'bg-gray-800 text-gray-100 rounded-tl-sm'
                  : 'bg-brand-600 text-white rounded-tr-sm'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              <p className="text-xs opacity-50 mt-1">
                {message.timestamp.toLocaleTimeString()}
              </p>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3">
              <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex gap-3 bg-gray-900 rounded-xl border border-gray-800 p-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder='Ask anything — "Create a ₹500 sandbox payment"'
          className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 outline-none"
          disabled={isLoading}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          className="btn-primary px-3 py-1.5"
          aria-label="Send message"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
