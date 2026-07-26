import "@xterm/xterm/css/xterm.css";

/**
 * O IDE usa a largura inteira da janela, ao contrário das telas de gestão que
 * vivem num container centralizado.
 */
export default function IdeLayout({ children }: { children: React.ReactNode }) {
  return <div className="ide-shell">{children}</div>;
}
