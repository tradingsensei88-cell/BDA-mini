import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import MainLayout from "@/components/layout/MainLayout";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "CyberShield AI - Big Data Cyber Attack Detection",
    template: "%s | CyberShield AI",
  },
  description:
    "Real-time cyber attack detection platform: streaming network telemetry, anomaly detection, ML-powered threat classification, and SOC-grade alerting.",
  applicationName: "CyberShield AI",
  keywords: [
    "cybersecurity",
    "threat detection",
    "big data",
    "Apache Spark",
    "Kafka",
    "anomaly detection",
  ],
};

export const viewport: Viewport = {
  themeColor: "#04070F",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-cyber-bg font-sans text-slate-200 antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-cyber-elevated focus:px-4 focus:py-2 focus:text-sm focus:text-cyber-accent"
        >
          Skip to main content
        </a>
        <MainLayout>{children}</MainLayout>
      </body>
    </html>
  );
}
