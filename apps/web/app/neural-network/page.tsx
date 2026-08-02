"use client";

import React, { useEffect, useRef, useState } from "react";
import { LocalDB, NeuralModel } from "@/lib/db";
import { useToast } from "@/components/Toast";

export default function NeuralNetworkPage() {
  const { addToast } = useToast();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Estado da arquitetura
  const [modelName, setModelName] = useState("Classificador Customizado 2026");
  const [inputNodes, setInputNodes] = useState(4);
  const [hiddenLayers, setHiddenLayers] = useState<number[]>([6, 4]);
  const [outputNodes, setOutputNodes] = useState(2);
  const [activation, setActivation] = useState<"relu" | "sigmoid" | "tanh" | "softmax">("relu");
  const [learningRate, setLearningRate] = useState(0.01);
  const [epochs, setEpochs] = useState(100);

  // Estado de simulação de treino
  const [isTraining, setIsTraining] = useState(false);
  const [currentEpoch, setCurrentEpoch] = useState(0);
  const [currentLoss, setCurrentLoss] = useState(0.85);
  const [currentAccuracy, setCurrentAccuracy] = useState(52.0);
  const [savedModels, setSavedModels] = useState<NeuralModel[]>([]);

  useEffect(() => {
    setSavedModels(LocalDB.getNeuralModels());
  }, []);

  // Desenha a rede no Canvas HTML5
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Estrutura completa de camadas: [Input, ...Hidden, Output]
    const layerSizes = [inputNodes, ...hiddenLayers, outputNodes];
    const totalLayers = layerSizes.length;

    // Calcular posições dos neurônios (x, y)
    const layerPositions: { x: number; y: number }[][] = [];

    const paddingX = 80;
    const layerGap = (width - paddingX * 2) / (totalLayers - 1 || 1);

    layerSizes.forEach((nodeCount, layerIdx) => {
      const x = paddingX + layerIdx * layerGap;
      const nodes: { x: number; y: number }[] = [];

      const nodeGap = Math.min(60, (height - 100) / (nodeCount + 1));
      const startY = (height - nodeGap * (nodeCount - 1)) / 2;

      for (let i = 0; i < nodeCount; i++) {
        nodes.push({ x, y: startY + i * nodeGap });
      }
      layerPositions.push(nodes);
    });

    // 1. Desenhar Conexões (Sinapses)
    for (let l = 0; l < layerPositions.length - 1; l++) {
      const currentLayer = layerPositions[l];
      const nextLayer = layerPositions[l + 1];

      currentLayer.forEach((fromNode, i) => {
        nextLayer.forEach((toNode, j) => {
          ctx.beginPath();
          ctx.moveTo(fromNode.x, fromNode.y);
          ctx.lineTo(toNode.x, toNode.y);

          // Efeito visual de gradiente e pulso durante treino
          const alpha = 0.15 + (Math.sin(l + i + j + (isTraining ? Date.now() / 200 : 0)) + 1) * 0.1;
          ctx.strokeStyle = isTraining ? `rgba(59, 130, 246, ${alpha + 0.2})` : `rgba(255, 255, 255, ${alpha})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        });
      });
    }

    // 2. Desenhar Neurônios (Nós)
    layerPositions.forEach((layer, lIdx) => {
      const isInput = lIdx === 0;
      const isOutput = lIdx === layerPositions.length - 1;

      layer.forEach((node, nIdx) => {
        ctx.beginPath();
        ctx.arc(node.x, node.y, 14, 0, Math.PI * 2);

        if (isInput) {
          ctx.fillStyle = "#3b82f6"; // Azul para entrada
        } else if (isOutput) {
          ctx.fillStyle = "#10b981"; // Verde para saída
        } else {
          ctx.fillStyle = "#8b5cf6"; // Roxo para camadas ocultas
        }

        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();

        // Rótulo interno do nó
        ctx.fillStyle = "#ffffff";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const label = isInput ? `X${nIdx + 1}` : isOutput ? `Y${nIdx + 1}` : `h${nIdx + 1}`;
        ctx.fillText(label, node.x, node.y);
      });

      // Título da Camada
      ctx.fillStyle = "#94a3b8";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      const layerTitle = isInput ? "Entrada" : isOutput ? "Saída" : `Oculta ${lIdx}`;
      ctx.fillText(layerTitle, paddingX + lIdx * layerGap, height - 20);
    });
  }, [inputNodes, hiddenLayers, outputNodes, isTraining]);

  // Executa o treino simulado
  const handleStartTraining = () => {
    if (isTraining) return;
    setIsTraining(true);
    setCurrentEpoch(0);
    setCurrentLoss(0.92);
    setCurrentAccuracy(48.5);

    let step = 0;
    // ✅ FIX: Usar ref para acurácia final evita stale closure no toast
    let finalAccuracy = 48.5;
    const interval = setInterval(() => {
      step += 1;
      setCurrentEpoch(step);
      setCurrentLoss((prev) => Math.max(0.04, Number((prev * 0.94 - Math.random() * 0.02).toFixed(4))));
      setCurrentAccuracy((prev) => {
        const next = Math.min(99.4, Number((prev + (100 - prev) * 0.08).toFixed(2)));
        finalAccuracy = next;
        return next;
      });

      if (step >= epochs) {
        clearInterval(interval);
        setIsTraining(false);

        // ✅ INTEGRAÇÃO AUDITORIA
        LocalDB.addAuditLog({
          actor: "Treinador de Rede Neural",
          module: "Neural",
          action: "Treinamento de Arquitetura",
          details: `Rede Neural "${modelName}" treinada por ${epochs} épocas. Acurácia atingida: ${finalAccuracy.toFixed(1)}%.`,
          riskLevel: "low",
          ipAddress: "127.0.0.1",
          status: "success",
        });

        addToast(`Treinamento concluído! Acurácia final: ${finalAccuracy.toFixed(1)}%`, "success");
      }
    }, 40);
  };

  // Salvar modelo no Banco de Dados
  const handleSaveModel = () => {
    const newModel: NeuralModel = {
      id: `model-${Date.now()}`,
      name: modelName,
      architecture: {
        inputNodes,
        hiddenLayers,
        outputNodes,
        activation,
      },
      accuracy: currentAccuracy > 52 ? currentAccuracy : 95.4,
      epochsTrained: epochs,
      savedAt: new Date().toISOString(),
    };

    const updated = [newModel, ...savedModels];
    setSavedModels(updated);
    LocalDB.saveNeuralModels(updated);

    // ✅ INTEGRAÇÃO AUDITORIA
    LocalDB.addAuditLog({
      actor: "Usuário Engenheiro de IA",
      module: "Neural",
      action: "Persistência de Modelo Neural",
      details: `Modelo "${newModel.name}" persistido no BD com topologia [${inputNodes}, ${hiddenLayers.join(",")}, ${outputNodes}].`,
      riskLevel: "low",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast(`Modelo "${modelName}" salvo com sucesso no banco de dados!`, "success");
  };

  const handleAddHiddenLayer = () => {
    if (hiddenLayers.length >= 4) {
      addToast("Máximo de 4 camadas ocultas permitido no simulador.", "warning");
      return;
    }
    setHiddenLayers([...hiddenLayers, 4]);
  };

  const handleRemoveHiddenLayer = () => {
    if (hiddenLayers.length <= 1) return;
    setHiddenLayers(hiddenLayers.slice(0, -1));
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">🎨 Demo / Visualização</span>
          <h1>Simulador & Visualizador de Rede Neural</h1>
          <p>
            Ajuste topologias, funções de ativação e visualize a dinâmica de aprendizado em tempo
            real — simulação client-side, sem treino real nem conexão com o backend.
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn-primary glow-button"
            onClick={handleStartTraining}
            disabled={isTraining}
          >
            {isTraining ? `Treinando Epoch ${currentEpoch}/${epochs}...` : "▶ Iniciar Treinamento"}
          </button>
          <button type="button" className="btn-secondary" onClick={handleSaveModel}>
            💾 Salvar Modelo no BD
          </button>
        </div>
      </div>

      <div className="grid grid-3-1">
        {/* Canvas de Desenho da Arquitetura */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Visualização Gráfica da Arquitetura</h3>
            <div className="status-pills">
              <span className="pill-blue">Input: {inputNodes}</span>
              <span className="pill-purple">Ocultas: {hiddenLayers.join(", ")}</span>
              <span className="pill-green">Output: {outputNodes}</span>
            </div>
          </div>

          <div className="canvas-wrapper">
            <canvas ref={canvasRef} width={750} height={380} className="neural-canvas" />
          </div>

          {/* Métricas de Treino */}
          <div className="metrics-bar">
            <div className="metric-box">
              <span className="metric-label">Epoch Atual</span>
              <span className="metric-value">{currentEpoch} / {epochs}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">Perda (Loss)</span>
              <span className="metric-value font-mono text-red">{currentLoss.toFixed(4)}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">Acurácia</span>
              <span className="metric-value font-mono text-green">{currentAccuracy.toFixed(2)}%</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">Função Ativação</span>
              <span className="metric-value text-uppercase">{activation}</span>
            </div>
          </div>
        </div>

        {/* Controles de Configuração da Rede */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Hiperparâmetros</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="model-name">Nome do Modelo</label>
              <input
                id="model-name"
                type="text"
                className="input-text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Neurônios de Entrada (Input)</label>
              <div className="number-stepper">
                <button type="button" onClick={() => setInputNodes(Math.max(1, inputNodes - 1))}>-</button>
                <span>{inputNodes}</span>
                <button type="button" onClick={() => setInputNodes(Math.min(12, inputNodes + 1))}>+</button>
              </div>
            </div>

            <div className="form-group">
              <label>Camadas Ocultas ({hiddenLayers.length})</label>
              <div className="layer-buttons">
                <button type="button" className="btn-secondary-sm" onClick={handleAddHiddenLayer}>+ Adicionar Camada</button>
                <button type="button" className="btn-secondary-sm" onClick={handleRemoveHiddenLayer}>- Remover</button>
              </div>
            </div>

            <div className="form-group">
              <label>Neurônios de Saída (Output)</label>
              <div className="number-stepper">
                <button type="button" onClick={() => setOutputNodes(Math.max(1, outputNodes - 1))}>-</button>
                <span>{outputNodes}</span>
                <button type="button" onClick={() => setOutputNodes(Math.min(8, outputNodes + 1))}>+</button>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="activation-select">Função de Ativação</label>
              <select
                id="activation-select"
                value={activation}
                onChange={(e) => setActivation(e.target.value as "relu" | "sigmoid" | "tanh" | "softmax")}
                className="input-select"
              >
                <option value="relu">ReLU (Rectified Linear Unit)</option>
                <option value="sigmoid">Sigmoid</option>
                <option value="tanh">Tanh (Tangente Hiperbólica)</option>
                <option value="softmax">Softmax (Multi-Classe)</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="lr-range">Taxa de Aprendizado (LR): {learningRate}</label>
              <input
                id="lr-range"
                type="range"
                min="0.001"
                max="0.1"
                step="0.001"
                value={learningRate}
                onChange={(e) => setLearningRate(parseFloat(e.target.value))}
                className="range-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="epochs-range">Total de Épocas: {epochs}</label>
              <input
                id="epochs-range"
                type="range"
                min="10"
                max="500"
                step="10"
                value={epochs}
                onChange={(e) => setEpochs(parseInt(e.target.value, 10))}
                className="range-input"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Modelos Salvos no Banco de Dados */}
      <section className="section-block">
        <h2 className="section-title">💾 Modelos Persistidos no Banco de Dados</h2>
        <div className="grid grid-3">
          {savedModels.map((m) => (
            <div key={m.id} className="model-saved-card">
              <div className="model-card-header">
                <h3>{m.name}</h3>
                <span className="badge-tag green">{m.accuracy}% Acurácia</span>
              </div>
              <p className="model-arch-text">
                Entrada: {m.architecture.inputNodes} · Ocultas: [{m.architecture.hiddenLayers.join(", ")}] · Saída: {m.architecture.outputNodes}
              </p>
              <div className="model-card-footer">
                <span>Ativação: {m.architecture.activation}</span>
                <span className="text-muted">{new Date(m.savedAt).toLocaleDateString("pt-BR")}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
