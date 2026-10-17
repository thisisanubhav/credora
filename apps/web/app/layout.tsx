import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Credora · Loan Eligibility",
  description: "Upload a CSV and follow its validation progress in the local environment.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
