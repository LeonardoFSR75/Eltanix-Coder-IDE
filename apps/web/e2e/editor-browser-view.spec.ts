import { test, expect } from "@playwright/test";

/**
 * Item 19 do plano de robustez do navegador interno: o e2e existente
 * (`browser-panel.spec.ts`) só cobre o painel lateral `BrowserPanel` — nunca
 * o navegador central de abas (`EditorBrowserView.tsx`, montado standalone
 * em `/browser`) nem o fluxo de modo Live com um hostname Docker-interno.
 *
 * Cobre exatamente o bug original que motivou a Fase 1 deste plano: um
 * hostname que só existe dentro de `browser_net` (`web`, `api`,
 * `novaai-studio-*`, ...) nunca deve virar `src` de um `<iframe>` renderizado no
 * navegador REAL do usuário sem aviso — a heurística client-side (item 5)
 * precisa barrar isso mesmo digitado direto na barra de endereço, sem
 * depender de nenhuma resposta do backend.
 */
test("modo Live avisa e nunca navega quando o host é Docker-interno", async ({ page }) => {
  await page.goto("/browser");

  const urlInput = page.getByLabel("Endereço da página");
  await expect(urlInput).toBeVisible({ timeout: 20_000 });

  // Modo Live é o padrão desta página (`initialMode` não é passado por
  // `app/browser/page.tsx`) — confirma antes de seguir, já que o aviso só
  // dispara nesse modo (fora dele o iframe nem existe).
  await expect(page.getByRole("button", { name: /Modo Live Iframe/i })).toHaveClass(/active/);

  const iframe = page.locator("iframe.browser-live-iframe");
  const srcAntes = await iframe.getAttribute("src");

  await urlInput.fill("http://web:5400/admin");
  await page.getByRole("button", { name: "Ir" }).click();

  const aviso = page.getByRole("alert");
  await expect(aviso).toBeVisible();
  await expect(aviso).toContainText("web");
  await expect(aviso).toContainText("Docker");

  // O src do iframe nunca chega a apontar pro host Docker-interno — nem
  // muda em relação ao que já estava lá (a correção do item 5 retorna ANTES
  // de qualquer atribuição imperativa a `iframeRef.current.src`).
  await expect(iframe).toHaveAttribute("src", srcAntes ?? "");
});

test("modo Live navega normalmente para um host público, sem aviso", async ({ page }) => {
  await page.goto("/browser");

  const urlInput = page.getByLabel("Endereço da página");
  await expect(urlInput).toBeVisible({ timeout: 20_000 });

  await urlInput.fill("http://localhost:5400");
  await page.getByRole("button", { name: "Ir" }).click();

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator("iframe.browser-live-iframe")).toHaveAttribute(
    "src",
    "http://localhost:5400",
  );
});
