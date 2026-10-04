import { useState } from 'react';
import { Send, Loader2, Bot, User, ShieldCheck, ShieldX } from 'lucide-react';
import { ApiError, needsAction, type Run } from '@/api/client';
import { platform, getToken, setToken } from '@/api/session';

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

/**
 * Chat page — sends requests to the platform API (POST /api/v1/runs) and shows the real
 * run outcome. Side-effecting actions stop for approval; the panel shows the exact action
 * and hash, and approving sends that hash back so the server rejects anything changed.
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
              className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm ${
                message.role === 'user'
                  ? 'bg-brand-600 text-white rounded-tr-sm'
                  : message.role === 'error'
                    ? 'bg-red-950 text-red-200 rounded-tl-sm'
                    : 'bg-gray-800 text-gray-100 rounded-tl-sm'
              }`}
            >
              {message.role === 'assistant' && message.run && (
                <p className="text-xs uppercase tracking-wider text-gray-400 mb-1">
                  {message.run.status} · {message.run.run_id} · {message.run.environment}
                </p>
              )}
              <p className="whitespace-pre-wrap">{message.content}</p>
              {message.role === 'assistant' &&
                message.run?.pending_approval &&
                needsAction(message.run) && (
                  <div className="mt-3 border border-amber-700 rounded-lg p-3 space-y-2">
                    <p className="text-amber-300 font-medium">Approval required</p>
                    <p>{message.run.pending_approval.summary}</p>
                    <p className="font-mono text-xs break-all text-gray-400">
                      action hash {message.run.pending_approval.action_hash}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => message.run && decide(message.run, true)}
                        disabled={isLoading}
                        className="btn-primary px-3 py-1 flex items-center gap-1"
                      >
                        <ShieldCheck className="w-4 h-4" /> Approve exactly this
                      </button>
                      <button
                        onClick={() => message.run && decide(message.run, false)}
                        disabled={isLoading}
                        className="px-3 py-1 rounded-lg border border-gray-700 flex items-center gap-1"
                      >
                        <ShieldX className="w-4 h-4" /> Reject
                      </button>
                    </div>
                  </div>
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
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3">
              <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
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
