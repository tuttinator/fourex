import Link from "next/link";
import { auth, signOut } from "@/auth";
import { Button } from "@/components/ui/button";

export async function SessionBar() {
  const session = await auth();

  return (
    <div className="flex items-center justify-end gap-3 border-b border-border/60 bg-background/60 px-4 py-2 text-sm">
      {session?.user?.email ? (
        <>
          <span className="text-muted-foreground">
            Signed in as <span className="font-medium text-foreground">{session.user.email}</span>
          </span>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/signin" });
            }}
          >
            <Button type="submit" size="sm" variant="ghost">
              Sign out
            </Button>
          </form>
        </>
      ) : (
        <Button asChild size="sm" variant="outline">
          <Link href="/signin">Sign in</Link>
        </Button>
      )}
    </div>
  );
}
