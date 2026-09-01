import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  title: 'GlassBox Alpha — Auditable AI Options Agent',
  description: 'A paper-only options agent that freezes every trade before AI review, enforces two independent veto layers, and proves decisions with a SHA-256 audit chain.',
  openGraph: {
    title: 'GlassBox Alpha — Auditable AI Options Agent',
    description: 'Freeze before AI. Two independent vetoes. One verifiable decision chain.',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'GlassBox Alpha social preview' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'GlassBox Alpha — Auditable AI Options Agent',
    description: 'Freeze before AI. Two independent vetoes. One verifiable decision chain.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
