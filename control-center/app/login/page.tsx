import { redirect } from "next/navigation";
import { demoEnabled, sessionSecret } from "@/lib/server/config";
import { currentSession } from "@/lib/server/session";
import { usersConfigured } from "@/lib/server/users";
import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  if (await currentSession()) redirect("/");
  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <div className="panel w-full max-w-sm space-y-6 p-6">
        <div className="space-y-1 text-center">
          <p className="text-[11px] tracking-[0.3em] text-accent">AI CONTROL CENTER</p>
          <h1 className="text-lg font-medium">ログイン</h1>
        </div>
        <LoginForm demo={demoEnabled()} usersConfigured={usersConfigured()} secretOk={sessionSecret() !== null} />
      </div>
    </main>
  );
}
