"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/", "ホーム"], ["/upcoming", "今後の指標"], ["/past", "過去の指標"], ["/lab", "AI研究室"],
  ["/accuracy", "予測精度"], ["/data", "データ"],
] as const;

export default function Nav() {
  const p = usePathname();
  return (
    <header className="sticky top-0 z-20 bg-bg/90 backdrop-blur border-b border-line">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 flex items-center gap-4 h-14">
        <Link href="/" className="font-bold text-gold whitespace-nowrap">XAUUSD<span className="text-slate-300 font-normal text-sm ml-1.5 hidden sm:inline">経済指標AI研究</span></Link>
        <nav className="flex gap-1 overflow-x-auto no-scrollbar text-sm">
          {LINKS.map(([href, label]) => {
            const active = href === "/" ? p === "/" : p.startsWith(href);
            return (
              <Link key={href} href={href}
                className={`px-2.5 py-1.5 rounded-md whitespace-nowrap ${active ? "bg-panel2 text-gold" : "text-slate-300 hover:text-white"}`}>
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
