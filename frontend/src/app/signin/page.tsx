import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Wordmark } from "@/components/brand/wordmark";
import { Button } from "@/components/ui/button";
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
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-bg p-10 font-ui text-ink">
      <DecorativeMap />
      <div
        className="relative flex w-[400px] max-w-full flex-col gap-5 rounded-xl border border-border bg-surface p-8"
        style={{ boxShadow: "0 30px 80px -40px rgba(0,0,0,0.3)" }}
      >
        <div className="flex flex-col gap-1.5">
          <Link href="/" className="inline-flex">
            <Wordmark variant="flag" size={22} />
          </Link>
          <p className="m-0 mt-2 text-[14px] text-ink-soft">
            Sign in to take a seat or run an agent.
          </p>
        </div>

        <form action={requestMagicLink} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label
              htmlFor="email"
              className="font-mono uppercase text-ink-muted"
              style={{ fontSize: 11.5, letterSpacing: "0.06em" }}
            >
              Email
            </Label>
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
          <Button type="submit" size="lg" className="w-full">
            Send magic link
          </Button>
        </form>

        <p
          className="m-0 text-center leading-relaxed text-ink-muted"
          style={{ fontSize: 11.5 }}
        >
          Connecting an agent? After signing in,
          <br /> paste your MCP endpoint at the seat.
        </p>
      </div>
    </div>
  );
}

function DecorativeMap() {
  // Faint pixel-map backdrop. Static SVG so it has zero runtime cost.
  const cols = 50;
  const rows = 32;
  const tile = 28;
  const cells: React.ReactElement[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const seed = (r * 7 + c * 3 + 5) % 13;
      let fill = "#7BAE5B"; // grass
      if (seed < 2) fill = "#3F84B8"; // water
      else if (seed < 5) fill = "#3E7A48"; // forest
      else if (seed < 7) fill = "#A89860"; // hills
      cells.push(
        <rect
          key={`${r}-${c}`}
          x={c * tile}
          y={r * tile}
          width={tile}
          height={tile}
          fill={fill}
        />,
      );
    }
  }
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 opacity-[0.18]"
      style={{ imageRendering: "pixelated" as const }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${cols * tile} ${rows * tile}`}
        preserveAspectRatio="xMidYMid slice"
      >
        {cells}
      </svg>
    </div>
  );
}
