"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Fronteira de erro por região da UI. Sem isto, um throw dentro de qualquer
 * painel do IDE (editor, dock do agente, terminal, um card de ferramenta que
 * recebeu um payload inesperado) derruba a rota `/ide` inteira para uma tela
 * branca. Aqui o erro fica contido no painel que falhou, com um botão para
 * remontar só aquele pedaço.
 *
 * Precisa ser class component: `getDerivedStateFromError`/`componentDidCatch`
 * não têm equivalente em hooks.
 */
interface Props {
  children: ReactNode;
  /** Nome da região, mostrado no aviso ("Editor", "Agente", "Terminal"…). */
  label?: string;
  /** Renderização alternativa custom; recebe o erro e um `reset`. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Chamado depois que o usuário clica em "Tentar novamente". */
  onReset?: () => void;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Sobe para o console com contexto — o overlay do Next em dev já mostra o
    // stack; em produção isto é o único registro.
    console.error(`[ErrorBoundary${this.props.label ? ` · ${this.props.label}` : ""}]`, error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div className="error-boundary-fallback" role="alert">
        <div className="error-boundary-title">
          {this.props.label ? `${this.props.label} falhou` : "Algo quebrou nesta área"}
        </div>
        <div className="error-boundary-message">{error.message || String(error)}</div>
        <button type="button" className="error-boundary-retry" onClick={this.reset}>
          Tentar novamente
        </button>
      </div>
    );
  }
}
