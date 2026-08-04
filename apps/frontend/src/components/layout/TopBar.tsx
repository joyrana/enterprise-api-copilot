export function TopBar() {
  return (
    <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center justify-between px-6">
      <div />
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-500 font-mono">
          Enterprise API Copilot
        </span>
        <div className="w-2 h-2 rounded-full bg-green-500" title="Backend connected" />
      </div>
    </header>
  );
}
