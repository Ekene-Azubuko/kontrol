import { notFound } from "next/navigation";
import { Workspace } from "@/components/workspace";
/** Resolve the two explicit application surfaces and reject unsupported routes. */
export default async function Page({
  params,
}: {
  params: Promise<{ role: string; page: string }>;
}) {
  const { role, page } = await params;
  if (role !== "coordinator" && role !== "resident") notFound();
  const pages =
    role === "coordinator"
      ? [
          "overview",
          "incidents",
          "resources",
          "response-plans",
          "dispatch",
          "hospitals",
          "communications",
          "agents",
        ]
      : ["home", "updates", "report", "help", "assistant"];
  if (!pages.includes(page)) notFound();
  return <Workspace role={role} page={page} />;
}
