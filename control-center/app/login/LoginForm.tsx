"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, sessionApi } from "@/lib/client/api";
import { Button, ErrorNote, Field, inputCls } from "@/components/ui/primitives";

export function LoginForm({ demo, usersConfigured, secretOk }: { demo: boolean; usersConfigured: boolean; secretOk: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState<"live" | "demo" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(body: Record<string, string>, kind: "live" | "demo") {
    setBusy(kind);
    setErr(null);
    try {
      await sessionApi.login(body);
      router.replace("/");
      router.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "ログインできませんでした");
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      {!secretOk && <ErrorNote>CC_SESSION_SECRET（32文字以上）が未設定のため、本番モードではログインできません。</ErrorNote>}
      {usersConfigured ? (
        <form className="space-y-3" onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          void submit({ username: String(f.get("username") ?? ""), password: String(f.get("password") ?? "") }, "live");
        }}>
          <Field label="ユーザー名"><input name="username" autoComplete="username" required className={inputCls} /></Field>
          <Field label="パスワード"><input name="password" type="password" autoComplete="current-password" required className={inputCls} /></Field>
          <Button type="submit" variant="primary" className="w-full" busy={busy === "live"}>実データでログイン</Button>
        </form>
      ) : (
        <p className="text-sm text-muted">実データ用のユーザー（CC_USERS）が未設定です。README の手順で設定してください。</p>
      )}
      {demo && (
        <div className="space-y-2 border-t border-line pt-4">
          <Button className="w-full" onClick={() => void submit({ mode: "demo" }, "demo")} busy={busy === "demo"}>デモで確認する</Button>
          <p className="text-xs text-muted">デモはローカルのデモ用エンジンだけに接続し、実際の投稿や外部APIの呼び出しは行いません。</p>
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
    </div>
  );
}
