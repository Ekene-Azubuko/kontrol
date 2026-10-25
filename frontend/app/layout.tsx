import type { Metadata } from "next";
import { Providers } from "@/lib/api";
import { branding } from "@/lib/branding";
import { StartupScreen } from "@/components/startup-screen";
import { LivePhoneProvider } from "@/lib/live-phone";
import { LivePhoneNotice } from "@/components/live-phone";
import "@fontsource-variable/inter";
import "./globals.css";
export const metadata: Metadata = {
  title: branding.applicationTitle,
  icons: {
    icon: { url: "/brand/kontrol-logo.png", type: "image/png" },
  },
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
        <Providers>
          <LivePhoneProvider>
            <StartupScreen>{children}</StartupScreen>
            <LivePhoneNotice />
          </LivePhoneProvider>
        </Providers>
      </body>
    </html>
  );
}
