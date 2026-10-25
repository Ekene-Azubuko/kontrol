import { notFound } from "next/navigation";
import { Workspace } from "@/components/workspace";
/** Resolve dispatcher pages and reject all retired resident routes. */
export default async function Page({
  params,
}: {
  params: Promise<{ role: string; page: string }>;
}) {
  const { role, page } = await params;
  if (role !== "coordinator") notFound();
  const pages = ["overview", "calls", "incidents", "response-plans", "dispatch", "agents"];
  if (!pages.includes(page)) notFound();
  return <Workspace role={role} page={page} />;
}
