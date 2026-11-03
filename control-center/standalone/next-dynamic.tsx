// Stand-in for next/dynamic: React.lazy + Suspense with the same loading fallback.
import { lazy, Suspense, type ComponentType, type ReactNode } from "react";

export default function dynamic<P extends object>(loader: () => Promise<{ default: ComponentType<P> }>, opts?: { loading?: () => ReactNode }) {
  const L = lazy(loader);
  return function Dyn(props: P) {
    return <Suspense fallback={opts?.loading ? opts.loading() : null}><L {...props} /></Suspense>;
  };
}
