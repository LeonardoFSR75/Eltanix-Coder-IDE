export function ErrorNotice({ error }: { error: string }) {
  return (
    <div className="notice">
      <strong>Não foi possível carregar os dados.</strong>
      <br />
      {error}
      <br />
      <br />
      Verifique se o backend está no ar:
      <br />
      <code>cd apps/api && uv run uvicorn novaai_studio.main:app --port 8000</code>
    </div>
  );
}
