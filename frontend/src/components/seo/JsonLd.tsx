/**
 * Renders schema.org objects as `<script type="application/ld+json">`.
 *
 * A server component on purpose: the markup is static per route and needs no
 * hydration. `<` is escaped so a `</script>` inside any string field (an FAQ
 * answer, an article deck) cannot close the tag early.
 */
export function JsonLd({ data }: { data: Record<string, unknown> | Record<string, unknown>[] }) {
  const items = Array.isArray(data) ? data : [data];
  return (
    <>
      {items.map((item, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(item).replace(/</g, '\\u003c') }}
        />
      ))}
    </>
  );
}
