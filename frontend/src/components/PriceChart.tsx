"use client";
import { useEffect, useRef } from "react";
import { createChart, type UTCTimestamp } from "lightweight-charts";

interface Bar { time: number; open: number; high: number; low: number; close: number }

const jstTime = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false });

export default function PriceChart({ bars, releaseAt, basePrice }: { bars: Bar[]; releaseAt: string; basePrice?: number | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart = createChart(ref.current, {
      height: 320,
      layout: { background: { color: "#121826" }, textColor: "#aab3c5" },
      grid: { vertLines: { color: "#1c2438" }, horzLines: { color: "#1c2438" } },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: number) => jstTime(t) },
      localization: { locale: "ja-JP", timeFormatter: (t: number) => jstTime(t) },
      autoSize: true,
    });
    const s = chart.addCandlestickSeries({
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    s.setData(bars.map((b) => ({ ...b, time: b.time as UTCTimestamp })));
    const rel = Math.floor(new Date(releaseAt).getTime() / 1000);
    const mk = bars.find((b) => b.time >= rel);
    if (mk) s.setMarkers([{ time: mk.time as UTCTimestamp, position: "aboveBar", color: "#e9b949", shape: "arrowDown", text: "発表" }]);
    if (basePrice) s.createPriceLine({ price: basePrice, color: "#e9b949", lineStyle: 2, lineWidth: 1, title: "発表直前" });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, releaseAt, basePrice]);
  if (bars.length === 0)
    return <div className="text-sm text-muted p-6 text-center border border-dashed border-line rounded-lg">価格データ未取込（「データ」画面からTradingView CSVをインポートしてください）</div>;
  return <div ref={ref} className="w-full h-[320px]" />;
}
