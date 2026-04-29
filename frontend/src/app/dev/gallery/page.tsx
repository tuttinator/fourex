"use client";

import { notFound } from "next/navigation";

import { Identity } from "@/components/brand/identity";
import { PLAYER_PALETTE } from "@/components/brand/palette";
import { Wordmark, type WordmarkVariant } from "@/components/brand/wordmark";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Panel } from "@/components/ui/panel";
import { Stat, StatPair } from "@/components/ui/stat";
import { Tag, type TagTone } from "@/components/ui/tag";

const WORDMARK_VARIANTS: WordmarkVariant[] = ["flag", "monogram", "stamp", "plain"];
const TAG_TONES: TagTone[] = [
  "neutral",
  "accent",
  "success",
  "warning",
  "live",
  "destructive",
];

export default function GalleryPage() {
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_ENABLE_DEV_GALLERY !== "1") {
    notFound();
  }

  return (
    <div className="min-h-full bg-bg text-ink font-ui">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-bg-subtle px-6 py-3">
        <div className="flex items-center gap-3">
          <Wordmark variant="flag" size={22} />
          <span
            className="font-mono uppercase text-ink-muted"
            style={{ fontSize: 11, letterSpacing: "0.10em" }}
          >
            dev · gallery
          </span>
        </div>
        <ThemeToggle />
      </header>

      <main className="grid gap-6 px-6 py-8 md:grid-cols-2">
        <Section kicker="brand" title="Wordmark">
          <div className="flex flex-wrap items-center gap-8">
            {WORDMARK_VARIANTS.map((v) => (
              <div key={v} className="flex flex-col items-center gap-2">
                <Wordmark variant={v} size={32} />
                <span
                  className="font-mono uppercase text-ink-muted"
                  style={{ fontSize: 10.5, letterSpacing: "0.08em" }}
                >
                  {v}
                </span>
              </div>
            ))}
          </div>
        </Section>

        <Section kicker="brand" title="Identity">
          <div className="flex flex-wrap items-center gap-6">
            <Identity
              kind="human"
              name="Caleb"
              color={PLAYER_PALETTE[0].hex}
              showLabel
              label="seat 1"
            />
            <Identity
              kind="agent"
              id="agent-strategist"
              name="strategist"
              color={PLAYER_PALETTE[3].hex}
              showLabel
              label="agent"
            />
            <Identity kind="human" name="Mira" color={PLAYER_PALETTE[5].hex} />
            <Identity
              kind="agent"
              id="agent-2"
              color={PLAYER_PALETTE[7].hex}
            />
          </div>
        </Section>

        <Section kicker="primitives" title="Tag tones">
          <div className="flex flex-wrap items-center gap-2">
            {TAG_TONES.map((tone) => (
              <Tag key={tone} tone={tone}>
                {tone}
              </Tag>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {TAG_TONES.map((tone) => (
              <Tag key={`m-${tone}`} tone={tone} mono>
                {tone}
              </Tag>
            ))}
          </div>
        </Section>

        <Section kicker="primitives" title="Kbd">
          <div className="flex flex-wrap items-center gap-3 text-ink-muted">
            <Kbd>↵</Kbd>
            <Kbd>R</Kbd>
            <Kbd>esc</Kbd>
            <span style={{ fontSize: 13 }}>
              press <Kbd>?</Kbd> to open the help panel
            </span>
          </div>
        </Section>

        <Section kicker="primitives" title="Stat / StatPair">
          <div className="flex flex-wrap gap-8">
            <Stat value="2,418" label="games played" />
            <Stat value="36" label="agents" size="sm" />
            <Stat value="100%" label="reproducible" size="lg" />
          </div>
          <div className="mt-4 flex max-w-xs flex-col gap-1.5">
            <StatPair label="HP" value="12 / 18" />
            <StatPair label="moves" value="2 / 2" />
            <StatPair label="atk" value="6" />
            <StatPair label="def" value="4" />
            <StatPair label="upkeep" value="-3" accent="warning" />
            <StatPair label="income" value="+5" accent="success" />
          </div>
        </Section>

        <Panel title="Panel · with title only">
          <p className="m-0 text-sm text-ink-soft">
            Default Panel with a mono-uppercase header strip and 14px padding.
          </p>
        </Panel>

        <Panel
          kicker="kicker"
          title="Panel · kicker + action"
          action={
            <Button size="sm" variant="outline">
              action
            </Button>
          }
        >
          <p className="m-0 text-sm text-ink-soft">
            Header carries an accent kicker, the title, and a right-aligned action slot.
          </p>
        </Panel>

        <Panel padded={false}>
          <ul className="m-0 list-none p-0">
            {[1, 2, 3].map((i) => (
              <li
                key={i}
                className="flex items-center justify-between px-3.5 py-2.5 [&:not(:last-child)]:border-b [&:not(:last-child)]:border-border"
              >
                <Identity
                  kind={i === 2 ? "agent" : "human"}
                  id={`row-${i}`}
                  name={`row ${i}`}
                  color={PLAYER_PALETTE[i].hex}
                  size={20}
                  showLabel
                  label={`seat ${i}`}
                />
                <Tag tone={i === 1 ? "live" : "neutral"} mono>
                  {i === 1 ? "active" : "waiting"}
                </Tag>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="Panel · without border"
          bordered={false}
        >
          <p className="m-0 text-sm text-ink-soft">
            Used for embedded sub-panels where the parent already provides framing.
          </p>
        </Panel>

        <Section kicker="palette" title="Heraldic palette">
          <div className="flex flex-wrap gap-2">
            {PLAYER_PALETTE.map((p) => (
              <div
                key={p.id}
                className="flex flex-col items-center gap-1"
                style={{ width: 56 }}
              >
                <span
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 6,
                    background: p.hex,
                    boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.30)",
                  }}
                />
                <span
                  className="font-mono uppercase text-ink-muted"
                  style={{ fontSize: 10, letterSpacing: "0.06em" }}
                >
                  {p.name}
                </span>
              </div>
            ))}
          </div>
        </Section>
      </main>
    </div>
  );
}

function Section({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Panel kicker={kicker} title={title}>
      {children}
    </Panel>
  );
}
