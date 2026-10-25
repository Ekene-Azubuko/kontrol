import type { Metadata } from "next";
import { Providers } from "@/lib/api";
import { branding } from "@/lib/branding";
import "@fontsource-variable/inter";
import "./globals.css";
export const metadata: Metadata = {
  title: branding.applicationTitle,
  description:
    "SIMULATION (NOT FOR EMERGENCY USE). Recorded-call dispatcher co-pilot.",
};
/** Share authenticated queries and the local dispatcher identity across exercise pages. */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
