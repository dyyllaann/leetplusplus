import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Leet++ | Whiteboard practice",
  description: "Practice problem-solving aloud at your whiteboard.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}