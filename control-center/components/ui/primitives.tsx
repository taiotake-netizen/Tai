"use client";

import { AlertTriangle, CheckCircle2, Circle, CircleDashed, CircleDot, Loader2, X, XCircle } from "lucide-react";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Tone } from "@/lib/format";

export function Button({ variant = "default", busy, className = "", children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" | "ghost"; busy?: boolean }) {
  const v = {
    default: "border-line bg-panel-2 hover:border-[#24507c] text-text",
    primary: "border-accent/50 bg-accent/10 text-accent hover:bg-accent/20",
    danger: "border-error/40 bg-error/10 text-error hover:bg-error/20",
    ghost: "border-transparent bg-transparent text-muted hover:text-text hover:bg-white/5",
  }[variant];
  return (
    <button {...rest} disabled={rest.disabled || busy}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${v} ${className}`}>
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-ok border-ok/30 bg-ok/10",
  warn: "text-warn border-warn/30 bg-warn/10",
  error: "text-error border-error/30 bg-error/10",
  accent: "text-accent border-accent/30 bg-accent/10",
  muted: "text-muted border-line bg-white/[0.03]",
};

const TONE_ICON: Record<Tone, typeof Circle> = {
  ok: CheckCircle2, warn: AlertTriangle, error: XCircle, accent: CircleDot, muted: CircleDashed,
};

/** Status badge: always icon + text (never colour alone). */
export function Badge({ tone, children, spin }: { tone: Tone; children: ReactNode; spin?: boolean }) {
  const Icon = tone === "accent" && spin ? Loader2 : TONE_ICON[tone];
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] leading-4 ${TONE_CLASS[tone]}`}>
      <Icon className={`size-3 ${tone === "accent" && spin ? "animate-spin" : ""}`} aria-hidden />
      {children}
    </span>
  );
}

export function Panel({ title, action, children, className = "", id }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`panel min-w-0 p-4 ${className}`} aria-labelledby={title && id ? id : undefined}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 id={id} className="panel-title">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-sm text-muted">{children}</p>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="読み込み中">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-white/5" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg border border-error/30 bg-error/10 px-3 py-2 text-sm text-error">
      <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** Accessible side drawer (dialog). Focus is moved in, trapped by the browser's modal dialog, and restored on close. */
export function Drawer({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby={titleId}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
      className={`m-0 ml-auto h-dvh max-h-dvh w-full ${wide ? "sm:max-w-3xl" : "sm:max-w-xl"} border-l border-line bg-[#07111f] p-0 text-text backdrop:bg-black/60`}>
      {open && (
        <div className="flex h-full flex-col">
          <header className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 id={titleId} className="text-base font-medium">{title}</h2>
            <Button variant="ghost" onClick={onClose} aria-label="閉じる"><X className="size-4" /></Button>
          </header>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}

export function Confirm({ open, title, body, confirmLabel, danger, onConfirm, onCancel, requireText }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void; requireText?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onCancel} className="m-auto w-[min(92vw,440px)] rounded-xl border border-line bg-panel p-0 text-text backdrop:bg-black/60">
      {open && (
        <form method="dialog" className="space-y-4 p-5" onSubmit={(e) => {
          e.preventDefault();
          if (requireText && inputRef.current?.value !== requireText) return;
          onConfirm();
        }}>
          <h2 className="text-base font-medium">{title}</h2>
          <div className="text-sm text-muted">{body}</div>
          {requireText && (
            <label className="block text-sm">
              <span className="text-muted">確認のため「{requireText}」と入力</span>
              <input ref={inputRef} className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2" autoComplete="off" />
            </label>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={onCancel}>キャンセル</Button>
            <Button type="submit" variant={danger ? "danger" : "primary"}>{confirmLabel}</Button>
          </div>
        </form>
      )}
    </dialog>
  );
}

export type ToastMsg = { id: number; tone: Tone; text: string };

export function Toasts({ items, onDismiss }: { items: ToastMsg[]; onDismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`pointer-events-auto flex max-w-md items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg backdrop-blur ${TONE_CLASS[t.tone]}`}>
          <span className="min-w-0 flex-1 break-words">{t.text}</span>
          <button className="text-muted hover:text-text" onClick={() => onDismiss(t.id)} aria-label="通知を閉じる"><X className="size-4" /></button>
        </div>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-muted">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted/80">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text placeholder:text-muted/60";
