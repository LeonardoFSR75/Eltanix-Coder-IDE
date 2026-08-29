/**
 * Skeleton exibido enquanto o bundle da rota `/ide` (Monaco, xterm, dock do
 * agente — todos `dynamic`/`ssr:false`) baixa. Espelha o layout do shell
 * (barra de atividade + sidebar + editor + dock) para o primeiro paint não
 * "pular" quando o conteúdo real entra.
 */
export default function IdeLoading() {
  return (
    <div className="ide-container">
      <div className="ide-skeleton" aria-busy="true" aria-label="Carregando o IDE">
        <div className="ide-skeleton__activity" />
        <div className="ide-skeleton__sidebar">
          <div className="ide-skeleton__bar ide-skeleton__bar--title" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--mid" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--short" />
          <div className="ide-skeleton__bar ide-skeleton__bar--mid" />
        </div>
        <div className="ide-skeleton__main">
          <div className="ide-skeleton__bar ide-skeleton__bar--short" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--mid" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--short" />
        </div>
        <div className="ide-skeleton__dock">
          <div className="ide-skeleton__bar ide-skeleton__bar--title" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
          <div className="ide-skeleton__bar ide-skeleton__bar--mid" />
          <div className="ide-skeleton__bar ide-skeleton__bar--wide" />
        </div>
      </div>
    </div>
  );
}
