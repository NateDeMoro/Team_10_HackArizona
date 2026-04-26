import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Nuclear Cooling-Water Derating Forecaster",
  description:
    "1–14 day weather-driven derating forecasts for US nuclear plants.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-white text-[var(--ua-navy)]">
        <div className="h-1.5 w-full bg-[var(--ua-red)]" />
        <header className="border-b border-[var(--ua-navy)]/15 bg-white">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
            <Link href="/" className="flex items-center gap-3">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ua-red)] font-bold text-white">
                A
              </span>
              <span className="text-sm font-semibold tracking-tight text-[var(--ua-navy)]">
                Derating Forecaster
              </span>
            </Link>
            <span className="text-xs text-[var(--ua-navy)]/60">
              HackArizona · Team 10
            </span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
