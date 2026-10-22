import { Group, Text } from "@mantine/core";
import { PRODUCT } from "@/lib/product";

/** The mark: Ariadne's thread winding out of a labyrinth to its goal. */
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#0b7a84" />
      <path d="M8 25V10a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-4" stroke="#fff" strokeWidth="2.4"
        fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="13" cy="13.2" r="2.5" fill="#ffd166" />
    </svg>
  );
}

export function Logo({ size = 22, inverted = false }: { size?: number; inverted?: boolean }) {
  return (
    <Group gap={8} wrap="nowrap">
      <LogoMark size={size} />
      <Text fw={650} size={size >= 30 ? "xl" : "md"} c={inverted ? "white" : undefined} style={{ letterSpacing: -0.2 }}
        data-testid="product-name">
        {PRODUCT}
      </Text>
    </Group>
  );
}
