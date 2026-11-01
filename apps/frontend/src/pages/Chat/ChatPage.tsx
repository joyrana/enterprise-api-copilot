import { useState } from 'react';
import Markdown from 'react-markdown';
import { Send, Loader2, Bot, User, Sparkles } from 'lucide-react';
import { ApiError, type Run } from '@/api/client';
import { platform, getToken, setToken } from '@/api/session';
import { GenUI } from '@/components/genui/GenUI';

type Message =
  | { id: string; role: 'user'; content: string; timestamp: Date }
  | { id: string; role: 'assistant'; content: string; timestamp: Date; run?: Run }
  | { id: string; role: 'error'; content: string; timestamp: Date };

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.code} (HTTP ${err.status}): ${err.message}${err.requestId ? ` — request ${err.requestId}` : ''}`;
  }
  return err instanceof Error ? err.message : 'Unexpected error';
}

function runBadge(run: Run): string {
  const parts: string[] = [run.status, run.intent ?? 'no intent'];
  if (run.mode === 'agentic' && run.model) {
    parts.push(
      `${run.model.model} · ${run.model.calls} LLM calls · ${(run.elapsed_s ?? 0).toFixed(1)}s`
    );
  } else {
    parts.push(run.model?.fallbacks ? 'deterministic (LLM unavailable)' : 'deterministic');
  }
  parts.push(run.environment);
  return parts.join(' · ');
}

/**
 * Chat page — sends requests to the platform API (POST /api/v1/runs) and shows the real
 * run outcome: the agent's markdown reply plus the components it chose from the
 * component registry (generative UI). Side-effecting actions stop for approval; the panel
 * shows the exact action and hash, and approving sends that hash back so the server
 * rejects anything changed.
 */
export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [signedIn, setSignedIn] = useState<boolean>(() => getToken() !== null);
  const [devUser, setDevUser] = useState('alice');

  const append = (message: Message) => setMessages((prev) => [...prev, message]);
  const stamp = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const signIn = async () => {
    try {
      const token = await platform.devToken(devUser.trim());
      setToken(token.access_token);
      setSignedIn(true);
    } catch (err) {
      append({
        id: stamp(),
        role: 'error',
        content: `Sign-in failed: ${describeError(err)}`,
        timestamp: new Date(),
      });
    }
  };

  const showRun = (run: Run) =>
    append({ id: stamp(), role: 'assistant', content: run.message, timestamp: new Date(), run });

  const handleSend = async () => {
    const query = input.trim();
    if (!query || isLoading) return;
    append({ id: stamp(), role: 'user', content: query, timestamp: new Date() });
    setInput('');
    setIsLoading(true);
    try {
      showRun(await platform.createRun(query));
    } catch (err) {
      append({ id: stamp(), role: 'error', content: describeError(err), timestamp: new Date() });
    } finally {
      setIsLoading(false);
    }
  };

  const decide = async (run: Run, approve: boolean) => {
    if (!run.pending_approval) return;
    setIsLoading(true);
    try {
      const updated = approve
        ? await platform.approveRun(run.run_id, run.pending_approval.action_hash)
        : await platform.rejectRun(run.run_id, 'rejected in web app');
      showRun(updated);
    } catch (err) {
      append({ id: stamp(), role: 'error', content: describeError(err), timestamp: new Date() });
    } finally {
      setIsLoading(false);
    }
  };

  if (!signedIn) {
    return (
      <div className="max-w-md mx-auto mt-16 card space-y-4">
        <h1 className="text-xl font-bold text-white">Sign in</h1>
        <p className="text-sm text-gray-400">
          Local development sign-in (synthetic users). Production sign-in uses the platform&apos;s
          identity provider.
        </p>
        <label className="block text-sm text-gray-300" htmlFor="dev-user">
          Development user
        </label>
        <input
          id="dev-user"
          value={devUser}
          onChange={(e) => setDevUser(e.target.value)}
          className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-100"
        />
        <button onClick={signIn} className="btn-primary px-3 py-1.5">
          Sign in
        </button>
        {messages
          .filter((m) => m.role === 'error')
          .map((m) => (
            <p key={m.id} role="alert" className="text-sm text-red-400">
              {m.content}
            </p>
          ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] max-w-4xl mx-auto">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-white">Chat</h1>
        <p className="text-gray-400 text-sm mt-1">
          Requests run against the configured environment (sandbox by default). Writes always need
          an approver.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 mb-4" aria-live="polite">
        {messages.length === 0 && (
          <p className="text-sm text-gray-500">
            Try “Which API refunds a payment?” or “Create a payment of ₹500 for customer
            cust_acm0001”.
          </p>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
          >
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                message.role === 'user'
                  ? 'bg-gray-700'
                  : message.role === 'error'
                    ? 'bg-red-700'
                    : 'bg-brand-600'
              }`}
            >
              {message.role === 'user' ? (
                <User className="w-4 h-4 text-gray-300" />
              ) : (
                <Bot className="w-4 h-4 text-white" />
              )}
            </div>
            <div
              role={message.role === 'error' ? 'alert' : undefined}
              className={`${message.role === 'assistant' ? 'max-w-[90%] min-w-0' : 'max-w-[75%]'} rounded-2xl px-4 py-3 text-sm ${
                message.role === 'user'
                  ? 'bg-brand-600 text-white rounded-tr-sm'
                  : message.role === 'error'
                    ? 'bg-red-950 text-red-200 rounded-tl-sm'
                    : 'bg-gray-800 text-gray-100 rounded-tl-sm'
              }`}
            >
              {message.role === 'assistant' && message.run && (
                <p
                  className="text-xs uppercase tracking-wider text-gray-400 mb-1 flex items-center gap-1"
                  title={message.run.run_id}
                >
                  {message.run.mode === 'agentic' && (
                    <Sparkles className="w-3 h-3 text-brand-500" />
                  )}
                  {runBadge(message.run)}
                </p>
              )}
              {message.role === 'assistant' ? (
                <div className="markdown">
                  <Markdown>{message.content}</Markdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
              {message.role === 'assistant' && message.run && (
                <GenUI
                  run={message.run}
                  busy={isLoading}
                  decide={(approve) => message.run && decide(message.run, approve)}
                />
              )}
              <p className="text-xs opacity-50 mt-1">{message.timestamp.toLocaleTimeString()}</p>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex gap-3" aria-label="Working">
            <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2 text-xs text-gray-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              Agent is classifying, planning and calling skills…
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3 bg-gray-900 rounded-xl border border-gray-800 p-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder='Ask anything — "Which API refunds a payment?"'
          aria-label="Message"
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
