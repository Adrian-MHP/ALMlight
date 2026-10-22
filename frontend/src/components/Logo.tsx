import { Group, Text } from "@mantine/core";

/** Wordmark: a small node graph (the digital thread) next to the product name. */
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <Group gap={8} wrap="nowrap">
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="var(--mantine-color-indigo-6)" />
        <path d="M9 22 L16 10 L23 22" stroke="white" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <circle cx="9" cy="22" r="3" fill="white" />
        <circle cx="16" cy="10" r="3" fill="white" />
        <circle cx="23" cy="22" r="3" fill="var(--mantine-color-teal-3)" />
      </svg>
      <Text fw={700} size={size >= 30 ? "xl" : "md"} style={{ letterSpacing: -0.3 }}>
        ALM<span style={{ fontWeight: 400 }}>light</span>
      </Text>
    </Group>
  );
}
