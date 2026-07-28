export default function IdeLoading() {
  return (
    <div className="ide-container">
      <div className="ide">
        <nav className="activity-bar" />
        <aside className="ide-sidebar" style={{ width: 260 }} />
        <main className="ide-main">
          <div className="editor-empty">carregando IDE…</div>
        </main>
      </div>
    </div>
  );
}
