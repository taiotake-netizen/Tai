"use client";
import Link from "next/link";
import { CATEGORY_JA } from "@/lib/format";
import { Loading, useApi } from "@/components/ui";

export default function LabPage() {
  const { data, error, loading } = useApi<{ category: string; events: number }[]>("/api/lab");
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">AI研究室</h1>
      <p className="text-xs text-muted">指標別に、過去の類似イベント・予測精度・値幅分布・反転パターン・教訓を比較します。</p>
      {!data ? <Loading error={error} loading={loading} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {data.map((c) => (
            <Link key={c.category} href={`/lab/${c.category}`} className="card hover:border-gold/50">
              <div className="font-semibold">{CATEGORY_JA[c.category] ?? c.category}</div>
              <div className="text-xs text-muted mt-1">登録イベント {c.events}件</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
