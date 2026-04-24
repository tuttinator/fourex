import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const metadata = {
  title: "Sign in to Parley",
};

type SignInPageProps = {
  searchParams?: Promise<{ error?: string | string[]; callbackUrl?: string | string[] }>;
};

function errorMessage(error: string | undefined): string | null {
  if (!error) return null;
  switch (error) {
    case "EmailSignin":
      return "We couldn’t send the magic link. Please try again.";
    case "Verification":
      return "This magic link has expired or was already used. Request a new one.";
    default:
      return "Sign-in failed. Please try again.";
  }
}

export default async function SignInPage({ searchParams }: SignInPageProps) {
  const session = await auth();
  if (session?.user) {
    redirect("/");
  }

  const resolved = (await searchParams) ?? {};
  const rawError = Array.isArray(resolved.error) ? resolved.error[0] : resolved.error;
  const rawCallback = Array.isArray(resolved.callbackUrl)
    ? resolved.callbackUrl[0]
    : resolved.callbackUrl;
  const message = errorMessage(rawError);

  async function requestMagicLink(formData: FormData) {
    "use server";
    const email = String(formData.get("email") ?? "").trim();
    if (!email) return;
    await signIn("resend", {
      email,
      redirectTo: rawCallback ?? "/",
    });
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-16">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in to Parley</CardTitle>
          <CardDescription>
            Enter your email and we’ll send you a magic link — no password needed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={requestMagicLink} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                required
              />
            </div>
            {message ? (
              <p role="alert" className="text-sm text-destructive">
                {message}
              </p>
            ) : null}
            <Button type="submit" className="w-full">
              Send magic link
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
