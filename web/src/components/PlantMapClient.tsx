"use client";

import nextDynamic from "next/dynamic";

// Next.js 16 forbids `ssr: false` dynamic imports from server components,
// so this wrapper holds the dynamic + ssr:false pair inside a client
// boundary. The page.tsx server component imports PlantMapClient directly
// and Next.js handles the server -> client transition.
const PlantMap = nextDynamic(() => import("@/components/PlantMap"), {
  ssr: false,
  loading: () => (
    <div
      style={{ height: 520 }}
      className="flex w-full items-center justify-center rounded-xl border border-[var(--ua-navy)]/30 bg-[var(--ua-navy)]/[0.03] text-sm text-[var(--ua-navy)]/70"
    >
      Loading map…
    </div>
  ),
});

export default PlantMap;
