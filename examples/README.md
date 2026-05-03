# Examples

Once the MCP is wired up, these prompts demonstrate the full surface.

## 1. Single design

> Use claude-design to make a landing hero for "Strata", a cold-storage backup
> service. Audience: indie developers. Tone: trustworthy, slightly nerdy. Mention
> immutable snapshots and a 7-day free trial. Dark mode, editorial layout, no
> stock photos.

## 2. Iterate

> Iterate on `<design-id>` — keep the layout but make the headline tighter and
> add a small ASCII-style diagram showing snapshot lineage.

## 3. Parallel variants (mood)

> Use design_variants on `<design-id>`, dimension=mood, count=4. I want to see
> playful, brutalist, editorial, and minimal takes on the same content.

## 4. Variants from brief

> design_variants with brief "Settings page for a meditation app — three
> sections: profile, notifications, billing. Iconography subtle.", dimension=
> typography, count=3.

## 5. Extract a system

> Extract a design system from `<id-1>`, `<id-2>`, `<id-3>`. Call it `bone`.

## 6. Apply a system

> Apply system `<system-id>` to a brief: "checkout success page, single column,
> with order summary on the right at desktop, stacked on mobile."

## 7. Browse

> Open the studio preview.

## 8. Export

> Export `<design-id>` to my desktop.
