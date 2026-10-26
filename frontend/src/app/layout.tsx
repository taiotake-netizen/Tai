import type { Metadata, Viewport } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "XAUUSD 経済指標AI研究",
  description: "ゴールドの米国経済指標発表時の値動きを予測・検証・改善する研究プラットフォーム",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0b0f17" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <Nav />
        <main className="max-w-7xl mx-auto px-3 sm:px-6 py-5">{children}</main>
        <footer className="max-w-7xl mx-auto px-3 sm:px-6 py-6 text-[11px] text-muted">
          研究用システム。自動売買・投資助言は行いません。未検証データは学習・精度評価の確定値に使用しません。
        </footer>
      </body>
    </html>
  );
}
