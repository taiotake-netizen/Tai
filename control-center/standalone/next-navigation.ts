// Stand-in for next/navigation in the standalone preview (no Next.js router there).
export function useRouter() {
  return { replace: () => window.location.reload(), refresh: () => undefined, push: () => undefined };
}
