import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { SiteHeader } from "@/components/site-header";
import { isDevelopmentData, loadEngineOutput } from "@/lib/data";
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
  title: { default: "Store Coach", template: "%s · Store Coach" },
  description:
    "Tells each area manager which stores are slipping, why, and the one thing to do about it today.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const data = loadEngineOutput();
  return (
    <html lang="en-IN" className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
      <body className="min-h-dvh">
        <SiteHeader
          generatedAt={data?.generated_at ?? null}
          asOf={data?.as_of ?? null}
          developmentData={isDevelopmentData()}
        />
        <main className="mx-auto w-full max-w-3xl px-4 pb-20 pt-8 sm:px-6 sm:pt-10">{children}</main>
        <footer className="mx-auto w-full max-w-3xl border-t border-line px-4 py-6 text-sm text-muted sm:px-6">
          Every figure on this site is computed from store data by fixed rules. No sign-in is needed.
        </footer>
      </body>
    </html>
  );
}
