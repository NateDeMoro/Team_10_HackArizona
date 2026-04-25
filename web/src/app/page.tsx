import { getHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let status = "unreachable";
  try {
    status = (await getHealth()).status;
  } catch {
    // leave as unreachable
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-50 font-sans dark:bg-black">
      <h1 className="text-2xl font-semibold tracking-tight text-black dark:text-zinc-50">
        Nuclear Cooling-Water Derating Forecaster
      </h1>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        API: <span className="font-mono">{status}</span>
      </p>
    </main>
  );
}
