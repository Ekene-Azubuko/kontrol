import type { Metadata } from "next";
import { Providers } from "@/lib/api";
import { branding } from "@/lib/branding";
import "@fontsource-variable/inter";
import "./globals.css";
export const metadata: Metadata = {
  title: branding.applicationTitle,
  description:
    "Kontrol Command and Kontrol Community, supported by Kontrol Agents.",
};
/** Share live queries and the built-in portal identity across both surfaces. */
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
