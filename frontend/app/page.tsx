import { redirect } from "next/navigation";

/**
 * Root route - the SOC dashboard lives at `/overview`.
 * Server-side redirect keeps the entry URL clean and instant.
 */
export default function HomePage() {
  redirect("/overview");
}
