import { redirect } from "next/navigation";
import { Console } from "@/components/Console";
import { currentSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export default async function Home() {
  const s = await currentSession();
  if (!s) redirect("/login");
  return <Console />;
}
