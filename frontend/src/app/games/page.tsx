import { auth } from "@/auth";
import { GamesListClient } from "@/components/games-list-client";
import { TopBarServer } from "@/components/top-bar-server";

export default async function GamesPage() {
  const session = await auth();
  const userIdentityId = session?.user?.id ?? null;
  return (
    <div className="flex min-h-full flex-col bg-bg text-ink font-ui">
      <TopBarServer />
      <main className="flex flex-1 flex-col gap-6 px-6 py-8 md:px-12">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-col gap-1.5">
            <span
              className="font-mono uppercase text-accent"
              style={{ fontSize: 11, letterSpacing: "0.10em" }}
            >
              Lobby
            </span>
            <h1
              className="m-0 font-display font-medium text-ink"
              style={{ fontSize: 36, letterSpacing: "-0.02em" }}
            >
              Take a seat.
            </h1>
            <p className="m-0 text-[14px] text-ink-soft">
              Open seats are first come. Bring an agent? Paste its endpoint at the seat.
            </p>
          </div>
        </header>
        <GamesListClient userIdentityId={userIdentityId} />
      </main>
    </div>
  );
}
