"use server";

import { signOut } from "@/auth";

// Server action exported as its own module so client components can import
// it directly. `<TopBar>` consumes this via a `signOutAction` prop, which
// keeps the client component free of any server-only `auth()` references.
export async function signOutAction(): Promise<void> {
  await signOut({ redirectTo: "/signin" });
}
