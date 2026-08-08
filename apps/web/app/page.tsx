import { redirect } from "next/navigation";

/**
 * A Central de Projetos é a landing real da plataforma — "entro pelo
 * projeto" é o modelo, não um painel solto sem contexto de projeto.
 */
export default function HomePage() {
  redirect("/projects");
}
