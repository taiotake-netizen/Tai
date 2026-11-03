import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI CONTROL CENTER",
  description: "Threads自動運用の監視・設定・操作",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#050B14", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
